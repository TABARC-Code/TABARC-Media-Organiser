"""Decide whether a candidate match is safe to accept, or needs a person to look.

Acceptance needs a strong title match, a clear winner over the runner-up,
and nothing contradicting the filename. Anything less goes to review, and
nothing is accepted just because it was the best of a poor set.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from tabarc_media.identity.parser import ParsedName
from tabarc_media.identity.providers import Candidate

ACCEPT_SCORE = 0.92
ACCEPT_MARGIN = 0.05
REVIEW_FLOOR = 0.50

_ARTICLES = ("the ", "a ", "an ")


def normalise(title: str) -> str:
    """Lowercase, ASCII-fold, drop punctuation and a leading article, collapse spaces."""
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = text.casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for art in _ARTICLES:
        if text.startswith(art) and len(text) > len(art):
            text = text[len(art):]
            break
    return text


def title_similarity(a: str, b: str) -> float:
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: float
    notes: tuple[str, ...] = field(default=())


def score(parsed: ParsedName, cand: Candidate) -> Scored:
    titles = [cand.title] + ([cand.original_title] if cand.original_title else [])
    sim = max(title_similarity(parsed.title or "", t) for t in titles)
    value = sim
    notes = [f"title {sim:.2f}"]

    if parsed.year is not None and cand.year is not None:
        gap = abs(parsed.year - cand.year)
        if gap == 0:
            value += 0.05
            notes.append("year matches")
        elif gap == 1:
            notes.append("year off by one")  # release vs premiere dates differ, don't penalise much
        else:
            value -= 0.20
            notes.append(f"year differs by {gap}")

    if parsed.is_episode and cand.kind != "tv":
        value -= 0.50
        notes.append("episode name but not a TV entry")

    value = max(0.0, min(1.0, value))
    return Scored(cand, round(value, 4), tuple(notes))


@dataclass(frozen=True)
class Decision:
    status: str  # "accept", "review" or "none"
    best: Scored | None
    ranked: tuple[Scored, ...]
    reason: str


def decide(parsed: ParsedName, candidates: list[Candidate],
           expected_kinds: frozenset[str] | None = None) -> Decision:
    if parsed.title is None:
        return Decision("review", None, (), "filename gave no usable title")

    pool = [c for c in candidates if not expected_kinds or c.kind in expected_kinds]
    ranked = tuple(sorted((score(parsed, c) for c in pool),
                          key=lambda s: (-s.score, s.candidate.provider, s.candidate.provider_id)))
    if parsed.needs_review:
        # A thin name is still searched, so a person has something to choose from,
        # but it can never be accepted automatically.
        best = ranked[0] if ranked and ranked[0].score >= REVIEW_FLOOR else None
        return Decision("review", best, ranked, "filename too thin to trust on its own")
    if not ranked or ranked[0].score < REVIEW_FLOOR:
        return Decision("none", None, ranked, "no candidate close enough")

    groups = _group(ranked)
    top = groups[0][0]
    others = [g[0] for g in groups[1:]]
    wanted = normalise(parsed.title)

    def exact(s: Scored) -> bool:
        names = [s.candidate.title] + ([s.candidate.original_title] if s.candidate.original_title else [])
        return wanted in {normalise(n) for n in names}

    # An exact title match is only challenged by other exact matches (a remake,
    # a same-name show). A near-miss like "Breaking Band" is not a rival.
    rivals = [o for o in others if exact(o)] if exact(top) else others
    runner_up = max((o.score for o in rivals), default=0.0)
    agreed = len(groups[0])

    if top.score >= ACCEPT_SCORE and top.score - runner_up >= ACCEPT_MARGIN:
        why = "clear winner" if agreed == 1 else f"clear winner, agreed by {agreed} sources"
        return Decision("accept", top, ranked, why)
    if top.score >= ACCEPT_SCORE:
        return Decision("review", top, ranked, "tie or near-tie with another candidate")
    return Decision("review", top, ranked, "best match not strong enough to accept")


def _group(ranked: tuple[Scored, ...]) -> list[list[Scored]]:
    """Merge candidates that are the same work reported by different sources.

    Same kind, same normalised title and same year from different providers is
    one work seen twice, which is corroboration and not a tie. Two entries from
    the same provider stay separate, because that really is ambiguous.
    """
    groups: list[list[Scored]] = []
    for item in ranked:
        c = item.candidate
        for g in groups:
            head = g[0].candidate
            if (head.kind == c.kind and head.year == c.year
                    and normalise(head.title) == normalise(c.title)
                    and all(m.candidate.provider != c.provider for m in g)):
                g.append(item)
                break
        else:
            groups.append([item])
    return groups
