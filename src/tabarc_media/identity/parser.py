"""Turn a media filename into a best-guess title, year and episode position.

The parser never guesses. If a name is too thin to trust, it says so with
`needs_review` set, and the caller sends it to the review queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Anything in this list ends the title. Release tags, codecs and resolutions.
_RELEASE_TAG = re.compile(
    r"(?i)(?:^|[\s._-])(?:"
    r"480p|576p|720p|1080p|2160p|4k|uhd|hdr|remux|bluray|blu-ray|bdrip|brrip|"
    r"web-?dl|webrip|web|hdtv|dvdrip|dvd|x264|x265|h\.?264|h\.?265|hevc|avc|"
    r"aac|ac3|dts|atmos|10bit|proper|repack|extended|unrated|directors\.cut"
    r")(?=$|[\s._-])"
)
_SXXEYY = re.compile(r"(?i)(?:^|[\s._-])S(\d{1,2})[ ._-]?E(\d{1,3})(?![\dE])")
_MULTI_EPISODE = re.compile(r"(?i)(?:^|[\s._-])S\d{1,2}[ ._-]?E\d{1,3}(?:[ ._-]?-?E\d{1,3})+(?=$|[\s._-])")
_NXNN = re.compile(r"(?<![\dA-Za-z])(\d{1,2})x(\d{2,3})(?![\dA-Za-z])")
_YEAR = re.compile(r"(?:^|[\s._(\[-])((?:19|20)\d{2})(?=$|[\s._)\]-])")
_BRACKETS = re.compile(r"\[[^\]]*\]|\{[^}]*\}")


@dataclass(frozen=True)
class ParsedName:
    """What the filename says. Missing fields are None, never guessed."""

    title: str | None
    year: int | None
    season: int | None
    episode: int | None
    unsupported: str | None  # set when the name is a form we don't handle
    needs_review: bool

    @property
    def is_episode(self) -> bool:
        return self.season is not None and self.episode is not None


def _clean(text: str) -> str:
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -([{")


def parse_filename(name: str) -> ParsedName:
    """Parse a filename (with or without its extension) into title, year and episode."""
    stem = name.rsplit(".", 1)[0] if "." in name and name.rsplit(".", 1)[1].isalnum() else name
    stem = _BRACKETS.sub(" ", stem)

    if _MULTI_EPISODE.search(stem):
        return ParsedName(None, None, None, None,
                          unsupported="multi-episode file", needs_review=True)

    season = episode = None
    cut = len(stem)

    m = _SXXEYY.search(stem)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        cut = min(cut, m.start())
    else:
        m = _NXNN.search(stem)
        if m:
            season, episode = int(m.group(1)), int(m.group(2))
            cut = min(cut, m.start())

    year = None
    for ym in _YEAR.finditer(stem):
        # A year at the very start is part of the title, e.g. "1917" or "2001 A Space Odyssey".
        if ym.start() == 0 or ym.start(1) == 0:
            continue
        if ym.start(1) < cut:
            year = int(ym.group(1))
            cut = min(cut, ym.start())
        break

    tag = _RELEASE_TAG.search(stem)
    if tag and tag.start() < cut:
        cut = tag.start()

    title = _clean(stem[:cut])
    if not title:
        return ParsedName(None, year, season, episode,
                          unsupported=None, needs_review=True)

    # Titles that are only digits or only a year are too thin to trust.
    needs_review = (
        (season is None and year is None)
        or len(title) < 2
        or title.isdigit()
    )
    return ParsedName(title, year, season, episode, unsupported=None,
                      needs_review=needs_review)
