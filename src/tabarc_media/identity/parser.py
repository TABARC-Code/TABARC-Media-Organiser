"""Turn a media filename into a best-guess title, year and episode position.

The parser never guesses. If a name is too thin to trust, it says so with
`needs_review` set, and the caller sends it to the review queue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

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
_SEASON_EPISODE_WORDS = re.compile(r"(?i)(?:^|[\s._-])season[ ._-]?(\d{1,2})[ ._-]+episode[ ._-]?(\d{1,3})(?![\dA-Za-z])")
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
    return _parse_stem(stem)


_SEASON_DIR = re.compile(r"(?i)^(?:season|series|s)[ ._-]?\d{1,2}$|^specials?$")


def parse_path(rel_path: str) -> ParsedName:
    """Parse a library-relative path, using the folders when the file name says too little.

    `Some Film (2019)/movie.mkv` takes its title and year from the folder.
    `Show Name/Season 2/S02E05.mkv` takes the show from the nearest folder
    that isn't a season folder. A file name that already says enough wins.
    """
    parts = [p for p in re.split(r"[\\/]", rel_path) if p]
    if not parts:
        return _parse_stem("")
    parsed = parse_filename(parts[-1])
    folders = parts[:-1]

    if parsed.unsupported:
        return parsed

    if parsed.title is None and parsed.is_episode:
        for folder in reversed(folders):
            if _SEASON_DIR.match(folder.strip()):
                continue
            fp = _parse_stem(folder)
            if fp.title:
                return ParsedName(fp.title, fp.year, parsed.season, parsed.episode,
                                  unsupported=None, needs_review=False)
            break
        return parsed

    if parsed.needs_review and not parsed.is_episode and folders:
        fp = _parse_stem(folders[-1])
        if fp.title and fp.year is not None and not fp.needs_review:
            return fp
    return parsed


def _parse_stem(stem: str) -> ParsedName:
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
    elif (m := _SEASON_EPISODE_WORDS.search(stem)):
        season, episode = int(m.group(1)), int(m.group(2))
        cut = min(cut, m.start())
    else:
        m = _NXNN.search(stem)
        if m:
            season, episode = int(m.group(1)), int(m.group(2))
            cut = min(cut, m.start())

    year = None
    latest = date.today().year + 1  # a release a year ahead is plausible, 2049 is a title
    found = []
    for ym in _YEAR.finditer(stem):
        # A year at the very start is part of the title, e.g. "1917" or "2001 A Space Odyssey".
        if ym.start() == 0 or ym.start(1) == 0:
            continue
        if int(ym.group(1)) > latest or ym.start(1) >= cut:
            continue
        found.append(ym)
    if found:
        # "Blade Runner 2049 (2017)": the bracketed year is the release year.
        # Otherwise the last one wins, since a year inside a title comes first.
        bracketed = [m for m in found if stem[m.start(1) - 1] in "(["]
        chosen = (bracketed or found)[-1]
        year = int(chosen.group(1))
        cut = min(cut, chosen.start())

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
