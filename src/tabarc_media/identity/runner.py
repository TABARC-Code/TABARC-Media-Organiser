"""Run identity lookups over what the inventory found.

Reads the catalogue, never the media. For each present video or book it
parses the path, asks the enabled providers, scores the answer and records it
in the review queue. Nothing here changes a file.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from tabarc_media.config.loader import Config
from tabarc_media.identity.parser import parse_path
from tabarc_media.identity.providers import (
    Client, OpenLibrary, ProviderError, TVmaze, Wikidata,
)
from tabarc_media.identity.queue import HUMAN_STATUSES, identify
from tabarc_media.identity.scoring import normalise

# Which providers are asked about which kind of file, in order.
ROUTES = {
    "video": ("wikidata", "tvmaze"),
    "book": ("openlibrary", "wikidata"),
}
EXPECTED_KINDS = {
    "video": frozenset({"film", "tv"}),
    "book": frozenset({"book"}),
}


class Memo:
    """Remembers answers for one run, failures included.

    A series with three hundred episodes would otherwise search for the same
    show three hundred times. A failed lookup is remembered too, so a provider
    that is down isn't hammered once per file.
    """

    def __init__(self, provider):
        self._provider = provider
        self.name = provider.name
        self.calls = 0
        self.failures = 0
        self._seen: dict[str, object] = {}

    def search(self, title: str, limit: int = 5):
        key = normalise(title)
        if key not in self._seen:
            self.calls += 1
            try:
                self._seen[key] = self._provider.search(title, limit)
            except ProviderError as exc:
                self.failures += 1
                self._seen[key] = exc
        result = self._seen[key]
        if isinstance(result, ProviderError):
            raise result
        return result


@dataclass
class IdentifySummary:
    considered: int = 0
    fresh_skipped: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    provider_calls: dict[str, int] = field(default_factory=dict)
    providers_failed: bool = False

    def bump(self, status: str) -> None:
        self.counts[status] = self.counts.get(status, 0) + 1


def build_providers(cfg: Config, client: Client | None = None) -> dict[str, Memo]:
    client = client or Client(cfg.providers.contact)
    made = {
        "wikidata": lambda: Wikidata(client, cfg.providers.language),
        "tvmaze": lambda: TVmaze(client),
        "openlibrary": lambda: OpenLibrary(client),
    }
    return {name: Memo(made[name]()) for name in cfg.providers.enabled}


def run_identify(conn: sqlite3.Connection, cfg: Config, *, limit: int | None = None,
                 providers: dict[str, Memo] | None = None, today: date | None = None,
                 progress: Callable[[int, int], None] | None = None) -> IdentifySummary:
    today = today or date.today()
    providers = providers if providers is not None else build_providers(cfg)
    summary = IdentifySummary()

    rows = conn.execute(
        "SELECT root, rel_path, media_kind FROM media_files "
        "WHERE present = 1 AND media_kind IN ('video', 'book') "
        "ORDER BY root, rel_path_raw"
    ).fetchall()

    known = {
        (r["root"], r["rel_path"]): (r["status"], r["updated_on"], r["providers_failed"])
        for r in conn.execute(
            "SELECT root, rel_path, status, updated_on, providers_failed FROM identity_matches")
    }
    stale_before = today - timedelta(days=cfg.providers.max_age_days)

    for i, r in enumerate(rows, 1):
        if limit is not None and summary.considered >= limit:
            break
        prior = known.get((r["root"], r["rel_path"]))
        if prior is not None:
            status, updated, failed = prior
            # A result built while a source was down is incomplete, so it is retried
            # on the next run however recent it is. A person's decision is never redone.
            if status in HUMAN_STATUSES or (not failed and date.fromisoformat(updated) > stale_before):
                summary.fresh_skipped += 1
                continue

        summary.considered += 1
        chosen = [providers[n] for n in ROUTES[r["media_kind"]] if n in providers]
        if not chosen:
            # Nothing enabled can answer for this kind, so there is no verdict to record.
            summary.bump("no_provider")
            continue
        outcome = identify(
            conn, root=r["root"], rel_path=r["rel_path"], parsed=parse_path(r["rel_path"]),
            providers=chosen, expected_kinds=EXPECTED_KINDS[r["media_kind"]], today=today,
        )
        summary.bump(outcome)
        if progress:
            progress(i, len(rows))

    summary.provider_calls = {name: m.calls for name, m in providers.items()}
    summary.providers_failed = any(m.failures for m in providers.values())
    return summary
