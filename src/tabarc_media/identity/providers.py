"""Keyless metadata providers: Wikidata, TVmaze and Open Library.

Every request goes through `Client`, which sends a User-Agent with a contact
string, applies a per-provider minimum interval, sets a timeout, and retries
only failures that might clear up (timeouts, 429, 5xx). A provider error is
returned to the caller as ProviderError and never touches stored metadata.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from tabarc_media import __version__ as VERSION
DEFAULT_TIMEOUT = 10.0
DEFAULT_ATTEMPTS = 3

# Intervals are deliberately conservative. None of the three publishes a
# hard limit we have confirmed, so we wait a full second between requests
# to each. Open Library's guidance is 1 request per second unidentified and
# 3 identified; one a second is safe for both.
MIN_INTERVAL = {"wikidata": 1.0, "tvmaze": 1.0, "openlibrary": 1.0}


class ProviderError(RuntimeError):
    """A provider call failed. `transient` means a retry later may succeed."""

    def __init__(self, provider: str, message: str, transient: bool):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.transient = transient


@dataclass(frozen=True)
class Candidate:
    """One possible match from one provider. Everything here came from that source."""

    provider: str
    provider_id: str
    title: str
    year: int | None
    kind: str  # "film", "tv" or "book"
    original_title: str | None
    language: str | None
    source_url: str | None
    retrieved_on: date
    licence: str


def _year(text: str | None) -> int | None:
    if not text:
        return None
    m = re.match(r"\s*((?:19|20)\d{2})", text)
    return int(m.group(1)) if m else None


class RateLimiter:
    """Minimum gap between calls to one provider. Clock and sleep are injectable for tests."""

    def __init__(self, interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            gap = self.interval - (now - self._last)
            if gap > 0:
                self._sleep(gap)
                now = self._clock()
        self._last = now


class Client:
    """Sends identified, timed, rate-limited, retried GET requests for JSON."""

    def __init__(self, contact: str, *, timeout: float = DEFAULT_TIMEOUT,
                 attempts: int = DEFAULT_ATTEMPTS,
                 opener: Callable[..., Any] = urllib.request.urlopen,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        contact = (contact or "").strip()
        if not contact:
            raise ValueError("A contact string is required so providers can reach the operator.")
        self.user_agent = f"TABARC-Media-Organiser/{VERSION} ({contact})"
        self.timeout = timeout
        self.attempts = attempts
        self._opener = opener
        self._sleep = sleep
        self._limiters = {
            name: RateLimiter(interval, clock=clock, sleep=sleep)
            for name, interval in MIN_INTERVAL.items()
        }

    def get_json(self, provider: str, url: str, params: dict[str, str]) -> Any:
        full = f"{url}?{urllib.parse.urlencode(params)}"
        delay = 1.0
        for attempt in range(1, self.attempts + 1):
            self._limiters[provider].wait()
            req = urllib.request.Request(full, headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            })
            try:
                with self._opener(req, timeout=self.timeout) as resp:
                    body = resp.read()
                return json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                transient = exc.code == 429 or exc.code >= 500
                err = ProviderError(provider, f"HTTP {exc.code}", transient)
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                err = ProviderError(provider, f"network error ({type(exc).__name__})", True)
            except (ValueError, UnicodeDecodeError):
                err = ProviderError(provider, "response was not valid JSON", False)
            if not err.transient or attempt == self.attempts:
                raise err
            self._sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")  # pragma: no cover


class TVmaze:
    """TV shows. Public API, no key. Data is CC BY-SA 4.0, attribution to tvmaze.com."""

    name = "tvmaze"
    licence = "CC BY-SA 4.0, attribution to tvmaze.com"
    url = "https://api.tvmaze.com/search/shows"

    def __init__(self, client: Client):
        self.client = client

    def search(self, title: str, limit: int = 5) -> list[Candidate]:
        data = self.client.get_json(self.name, self.url, {"q": title})
        today = date.today()
        out = []
        for hit in (data or [])[:limit]:
            show = hit.get("show") or {}
            if not show.get("id") or not show.get("name"):
                continue
            out.append(Candidate(
                provider=self.name,
                provider_id=str(show["id"]),
                title=show["name"],
                year=_year(show.get("premiered")),
                kind="tv",
                original_title=None,
                language=show.get("language"),
                source_url=show.get("url"),
                retrieved_on=today,
                licence=self.licence,
            ))
        return out


class Wikidata:
    """Films, TV and books by label. Structured data is CC0, no attribution required."""

    name = "wikidata"
    licence = "CC0 1.0"
    url = "https://www.wikidata.org/w/api.php"

    def __init__(self, client: Client, language: str = "en-gb"):
        self.client = client
        self.language = language

    def search(self, title: str, limit: int = 5) -> list[Candidate]:
        data = self.client.get_json(self.name, self.url, {
            "action": "wbsearchentities",
            "search": title,
            "language": self.language,
            "uselang": self.language,
            "type": "item",
            "limit": str(limit),
            "format": "json",
        })
        today = date.today()
        out = []
        for hit in (data or {}).get("search", [])[:limit]:
            desc = (hit.get("description") or "").lower()
            kind = _kind_from_description(desc)
            if kind is None:
                continue  # not a film, TV show or book, so not our business
            year_m = re.search(r"\b((?:18|19|20)\d{2})\b", desc)
            out.append(Candidate(
                provider=self.name,
                provider_id=hit["id"],
                title=hit.get("label", ""),
                year=int(year_m.group(1)) if year_m else None,
                kind=kind,
                original_title=None,
                language=self.language,
                source_url=f"https://www.wikidata.org/wiki/{hit['id']}",
                retrieved_on=today,
                licence=self.licence,
            ))
        return [c for c in out if c.title]


def _kind_from_description(desc: str) -> str | None:
    if "television series" in desc or "tv series" in desc or "television programme" in desc:
        return "tv"
    if "film" in desc or "movie" in desc:
        return "film"
    if "novel" in desc or "book" in desc:
        return "book"
    return None


class OpenLibrary:
    """Ebooks by title. No key. Licence of the data not yet confirmed, so it stays marked as such."""

    name = "openlibrary"
    licence = "unconfirmed, see ACKNOWLEDGEMENTS.md"
    url = "https://openlibrary.org/search.json"

    def __init__(self, client: Client):
        self.client = client

    def search(self, title: str, limit: int = 5) -> list[Candidate]:
        data = self.client.get_json(self.name, self.url, {
            "title": title,
            "limit": str(limit),
            "fields": "key,title,first_publish_year,language",
        })
        today = date.today()
        out = []
        for doc in (data or {}).get("docs", [])[:limit]:
            if not doc.get("key") or not doc.get("title"):
                continue
            langs = doc.get("language") or []
            out.append(Candidate(
                provider=self.name,
                provider_id=doc["key"],
                title=doc["title"],
                year=doc.get("first_publish_year"),
                kind="book",
                original_title=None,
                language=langs[0] if langs else None,
                source_url=f"https://openlibrary.org{doc['key']}",
                retrieved_on=today,
                licence=self.licence,
            ))
        return out
