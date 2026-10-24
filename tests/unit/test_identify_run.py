"""Identity runs over a real inventory of a throwaway library, with fake providers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from tabarc_media.catalogue.db import connect
from tabarc_media.config.loader import load_config
from tabarc_media.identity.providers import Candidate, ProviderError
from tabarc_media.identity.queue import resolve
from tabarc_media.identity.runner import Memo, run_identify
from tabarc_media.inspection.runner import run_inventory
from tests.conftest import write_config

TODAY = date(2026, 10, 24)


class Fake:
    def __init__(self, name, results=(), error=None):
        self.name = name
        self.results = list(results)
        self.error = error
        self.calls = 0

    def search(self, title, limit=5):
        self.calls += 1
        if self.error is not None:
            raise ProviderError(self.name, "down", transient=True)
        return list(self.results)


def cand(title, year, kind, pid="1", provider="wikidata"):
    return Candidate(provider=provider, provider_id=pid, title=title, year=year, kind=kind,
                     original_title=None, language="en-gb", source_url=None,
                     retrieved_on=TODAY, licence="CC0 1.0")


@pytest.fixture
def env(tmp_path, library):
    cfg_path = write_config(tmp_path / "c.toml", tmp_path / "db" / "c.sqlite3", [library],
                            '[providers]\ncontact = "ops@example.org"\nmax_age_days = 30\n')
    cfg = load_config(cfg_path)
    conn = connect(cfg.database_path)
    run_inventory(conn, cfg, probe=False)
    yield cfg, conn, library
    conn.close()


def memos(**fakes):
    return {name: Memo(f) for name, f in fakes.items()}


def status_of(conn, name_part):
    row = conn.execute("SELECT status FROM identity_matches WHERE rel_path LIKE ?",
                       (f"%{name_part}%",)).fetchone()
    return row["status"] if row else None


def test_video_and_book_are_identified_and_recorded(env):
    cfg, conn, _ = env
    wiki = Fake("wikidata", [cand("Arrival", 2016, "film")])
    s = run_identify(conn, cfg, providers=memos(wikidata=wiki, tvmaze=Fake("tvmaze"),
                                                 openlibrary=Fake("openlibrary")), today=TODAY)
    assert status_of(conn, "Arrival") == "matched"
    assert status_of(conn, "Title.epub") == "pending"  # a bare title is too thin to trust
    assert s.considered == 2 and s.counts == {"matched": 1, "pending": 1}
    assert s.providers_failed is False


def test_second_run_reuses_fresh_results_and_makes_no_calls(env):
    cfg, conn, _ = env
    wiki = Fake("wikidata", [cand("Arrival", 2016, "film")])
    ps = memos(wikidata=wiki, tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary"))
    run_identify(conn, cfg, providers=ps, today=TODAY)
    before = wiki.calls
    again = run_identify(conn, cfg, providers=ps, today=TODAY + timedelta(days=10))
    assert again.considered == 0 and again.fresh_skipped == 2
    assert wiki.calls == before


def test_stale_results_are_refreshed_after_max_age(env):
    cfg, conn, _ = env
    ps = memos(wikidata=Fake("wikidata", [cand("Arrival", 2016, "film")]),
               tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary"))
    run_identify(conn, cfg, providers=ps, today=TODAY)
    later = run_identify(conn, cfg, providers=memos(
        wikidata=Fake("wikidata", [cand("Arrival", 2016, "film")]),
        tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary")),
        today=TODAY + timedelta(days=31))
    assert later.considered == 2


def test_human_decision_is_never_refreshed_even_when_stale(env):
    cfg, conn, _ = env
    ps = memos(wikidata=Fake("wikidata"), tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary"))
    run_identify(conn, cfg, providers=ps, today=TODAY)
    rid = conn.execute("SELECT id FROM identity_matches WHERE rel_path LIKE '%Arrival%'"
                       ).fetchone()["id"]
    resolve(conn, rid, "reject")
    later = run_identify(conn, cfg, providers=memos(
        wikidata=Fake("wikidata", [cand("Arrival", 2016, "film")]),
        tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary")),
        today=TODAY + timedelta(days=400))
    assert status_of(conn, "Arrival") == "rejected"
    assert later.fresh_skipped >= 1


def test_a_whole_series_costs_one_lookup_per_provider(env):
    cfg, conn, lib = env
    season = lib / "TV" / "Show Name (2008)" / "Season 1"
    season.mkdir(parents=True)
    for n in range(1, 7):
        (season / f"S01E0{n}.mkv").write_bytes(b"x")
    run_inventory(conn, cfg, probe=False)
    tv = Fake("tvmaze", [cand("Show Name", 2008, "tv", pid="9", provider="tvmaze")])
    wiki = Fake("wikidata")
    ps = memos(wikidata=wiki, tvmaze=tv, openlibrary=Fake("openlibrary"))
    run_identify(conn, cfg, providers=ps, today=TODAY)
    # Seven video files (Arrival plus six episodes) but only two distinct titles.
    assert tv.calls == 2
    # Wikidata also backs up book lookups, so it sees Arrival, the show and the ebook.
    assert wiki.calls == 3
    rows = conn.execute("SELECT status FROM identity_matches WHERE rel_path LIKE '%S01E0%'"
                        ).fetchall()
    assert len(rows) == 6 and {r["status"] for r in rows} == {"matched"}


def test_failed_provider_is_remembered_flagged_and_writes_nothing(env):
    cfg, conn, lib = env
    season = lib / "TV" / "Show Name (2008)" / "Season 1"
    season.mkdir(parents=True)
    for n in range(1, 4):
        (season / f"S01E0{n}.mkv").write_bytes(b"x")
    run_inventory(conn, cfg, probe=False)
    tv = Fake("tvmaze", error=True)
    ps = {"tvmaze": Memo(tv)}
    s = run_identify(conn, cfg, providers=ps, today=TODAY)
    # Arrival and the show are two titles. The three episodes share one failed lookup.
    assert tv.calls == 2
    assert s.providers_failed is True
    assert conn.execute("SELECT COUNT(*) FROM identity_matches WHERE rel_path LIKE '%S01E0%'"
                        ).fetchone()[0] == 0


def test_kind_with_no_enabled_provider_records_nothing(env):
    cfg, conn, _ = env
    s = run_identify(conn, cfg, providers={}, today=TODAY)
    assert s.counts == {"no_provider": 2}
    assert conn.execute("SELECT COUNT(*) FROM identity_matches").fetchone()[0] == 0


def test_limit_caps_how_many_files_are_looked_up(env):
    cfg, conn, _ = env
    ps = memos(wikidata=Fake("wikidata"), tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary"))
    s = run_identify(conn, cfg, providers=ps, limit=1, today=TODAY)
    assert s.considered == 1


def test_a_result_built_while_a_source_was_down_is_retried_next_run(env):
    cfg, conn, _ = env
    down = memos(wikidata=Fake("wikidata", error=True), tvmaze=Fake("tvmaze"),
                 openlibrary=Fake("openlibrary", [cand("Title", None, "book")]))
    run_identify(conn, cfg, providers=down, today=TODAY)
    failed = conn.execute(
        "SELECT rel_path FROM identity_matches WHERE providers_failed != ''").fetchall()
    assert failed  # Arrival was recorded with wikidata marked as failed

    up = Fake("wikidata", [cand("Arrival", 2016, "film")])
    again = run_identify(conn, cfg, today=TODAY + timedelta(days=1), providers=memos(
        wikidata=up, tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary")))
    assert up.calls >= 1  # retried a day later, not reused for 30 days
    assert status_of(conn, "Arrival") == "matched"
    assert again.considered >= 1
