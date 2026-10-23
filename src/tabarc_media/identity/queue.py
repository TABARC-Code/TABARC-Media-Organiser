"""The identity review queue, kept in the catalogue.

Nothing here touches a media file. A row says what we think a file is, what
each source said, and whether a person has agreed. Renames come later, from a
saved plan.

Rules this module keeps:
- A human decision (accepted or rejected) is never overwritten by a later lookup.
- If every provider fails, nothing is written. A failed lookup is not a verdict.
- Each row keeps the source, licence and retrieval date of every candidate.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Iterable

from tabarc_media.identity.parser import ParsedName, parse_filename
from tabarc_media.identity.providers import ProviderError
from tabarc_media.identity.scoring import Decision, decide

HUMAN_STATUSES = ("accepted", "rejected")


def _candidate_dicts(decision: Decision) -> list[dict]:
    return [
        {
            "provider": s.candidate.provider,
            "provider_id": s.candidate.provider_id,
            "title": s.candidate.title,
            "year": s.candidate.year,
            "kind": s.candidate.kind,
            "score": s.score,
            "notes": list(s.notes),
            "source_url": s.candidate.source_url,
            "retrieved_on": s.candidate.retrieved_on.isoformat(),
            "licence": s.candidate.licence,
        }
        for s in decision.ranked[:5]
    ]


def identify(conn: sqlite3.Connection, *, root: str, rel_path: str, filename: str,
             providers: Iterable, expected_kinds: frozenset[str] | None = None,
             today: date | None = None) -> str:
    """Look a file up, score the result and record it. Returns the status written, or 'skipped'."""
    parsed: ParsedName = parse_filename(filename)
    today = today or date.today()
    providers = list(providers)  # may be a one-shot iterable; we count it below

    candidates, failed = [], []
    if parsed.title is not None and not parsed.needs_review:
        for provider in providers:
            try:
                candidates.extend(provider.search(parsed.title))
            except ProviderError as exc:
                failed.append(f"{exc.provider}:{'transient' if exc.transient else 'permanent'}")

        if providers and len(failed) == len(providers) and not candidates:
            return "skipped"  # every provider failed, so there is no verdict to record

    decision = decide(parsed, candidates, expected_kinds)
    status = {"accept": "matched", "review": "pending", "none": "none"}[decision.status]
    if parsed.title is None or parsed.needs_review:
        status = "pending"

    existing = conn.execute(
        "SELECT status FROM identity_matches WHERE root = ? AND rel_path = ?",
        (root, rel_path),
    ).fetchone()
    if existing is not None and existing["status"] in HUMAN_STATUSES:
        return "kept"  # a person already decided; a rescan doesn't undo that

    conn.execute(
        """
        INSERT INTO identity_matches
            (root, rel_path, status, reason, parsed_title, parsed_year, season, episode,
             candidates, providers_failed, updated_on)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (root, rel_path) DO UPDATE SET
            status = excluded.status,
            reason = excluded.reason,
            parsed_title = excluded.parsed_title,
            parsed_year = excluded.parsed_year,
            season = excluded.season,
            episode = excluded.episode,
            candidates = excluded.candidates,
            providers_failed = excluded.providers_failed,
            updated_on = excluded.updated_on
        """,
        (root, rel_path, status, decision.reason, parsed.title, parsed.year,
         parsed.season, parsed.episode, json.dumps(_candidate_dicts(decision)),
         ",".join(failed), today.isoformat()),
    )
    conn.commit()
    return status


def resolve(conn: sqlite3.Connection, row_id: int, action: str,
            provider: str | None = None, provider_id: str | None = None) -> None:
    """Record a person's decision. Accepting needs the provider and id they chose."""
    if action == "accept":
        if not provider or not provider_id:
            raise ValueError("accept needs the provider and provider id that were chosen")
        conn.execute(
            "UPDATE identity_matches SET status = 'accepted', chosen_provider = ?, chosen_id = ? "
            "WHERE id = ?",
            (provider, provider_id, row_id),
        )
    elif action == "reject":
        conn.execute(
            "UPDATE identity_matches SET status = 'rejected', chosen_provider = NULL, "
            "chosen_id = NULL WHERE id = ?",
            (row_id,),
        )
    else:
        raise ValueError(f"unknown action {action!r}")
    conn.commit()
