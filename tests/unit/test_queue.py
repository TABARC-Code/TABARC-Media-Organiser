from datetime import date

import pytest

from tabarc_media.catalogue import db
from tabarc_media.identity.providers import Candidate, ProviderError
from tabarc_media.identity.queue import identify, resolve


class Fake:
    def __init__(self, name, results=None, error=None):
        self.name = name
        self.results = results or []
        self.error = error
        self.calls = 0

    def search(self, title, limit=5):
        self.calls += 1
        if self.error is not None:
            raise ProviderError(self.name, "down", transient=self.error)
        return list(self.results)


def cand(title, year, pid="1", provider="wikidata", kind="film"):
    return Candidate(provider=provider, provider_id=pid, title=title, year=year, kind=kind,
                     original_title=None, language="en-gb", source_url=None,
                     retrieved_on=date(2026, 10, 24), licence="CC0 1.0")


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "catalogue.sqlite3")
    yield c
    c.close()


def row(conn, rel):
    return conn.execute("SELECT * FROM identity_matches WHERE rel_path = ?", (rel,)).fetchone()


def test_strong_match_is_recorded_as_matched_with_provenance(conn):
    p = Fake("wikidata", [cand("Some Film", 2019)])
    status = identify(conn, root="/r", rel_path="a.mkv", filename="Some Film (2019).mkv",
                      providers=[p], today=date(2026, 10, 24))
    assert status == "matched"
    r = row(conn, "a.mkv")
    assert r["status"] == "matched" and r["updated_on"] == "2026-10-24"
    assert "CC0 1.0" in r["candidates"] and "retrieved_on" in r["candidates"]


def test_weak_match_goes_to_pending_and_thin_name_never_calls_providers(conn):
    p = Fake("wikidata", [cand("Some Film", 1975)])
    assert identify(conn, root="/r", rel_path="b.mkv", filename="Some Film (2019).mkv",
                    providers=[p]) == "pending"
    q = Fake("wikidata", [cand("Random", None)])
    assert identify(conn, root="/r", rel_path="c.mkv", filename="Random.mkv",
                    providers=[q]) == "pending"
    assert q.calls == 0


def test_all_providers_failing_writes_nothing(conn):
    p = Fake("wikidata", error=True)
    q = Fake("tvmaze", error=False)
    assert identify(conn, root="/r", rel_path="d.mkv", filename="Some Film (2019).mkv",
                    providers=[p, q]) == "skipped"
    assert row(conn, "d.mkv") is None


def test_partial_failure_is_recorded_so_the_gap_is_visible(conn):
    ok = Fake("wikidata", [cand("Some Film", 2019)])
    bad = Fake("tvmaze", error=True)
    identify(conn, root="/r", rel_path="e.mkv", filename="Some Film (2019).mkv",
             providers=[ok, bad])
    assert row(conn, "e.mkv")["providers_failed"] == "tvmaze:transient"


def test_human_decision_survives_a_rescan(conn):
    identify(conn, root="/r", rel_path="f.mkv", filename="Some Film (2019).mkv",
             providers=[Fake("wikidata", [cand("Some Film", 1975)])])
    rid = row(conn, "f.mkv")["id"]
    resolve(conn, rid, "reject")
    again = identify(conn, root="/r", rel_path="f.mkv", filename="Some Film (2019).mkv",
                     providers=[Fake("wikidata", [cand("Some Film", 2019)])])
    assert again == "kept"
    assert row(conn, "f.mkv")["status"] == "rejected"


def test_accept_needs_the_provider_and_id(conn):
    identify(conn, root="/r", rel_path="g.mkv", filename="Some Film (2019).mkv",
             providers=[Fake("wikidata", [cand("Some Film", 1975)])])
    rid = row(conn, "g.mkv")["id"]
    with pytest.raises(ValueError):
        resolve(conn, rid, "accept")
    resolve(conn, rid, "accept", provider="wikidata", provider_id="Q1")
    r = row(conn, "g.mkv")
    assert (r["status"], r["chosen_provider"], r["chosen_id"]) == ("accepted", "wikidata", "Q1")


def test_v1_catalogue_migrates_to_v2_without_losing_rows(tmp_path):
    path = tmp_path / "old.sqlite3"
    c = db.connect(path)
    c.execute("DROP TABLE identity_matches")
    c.execute("UPDATE schema_info SET value = '1' WHERE key = 'version'")
    c.commit()
    c.close()

    c2 = db.connect(path)
    assert c2.execute("SELECT value FROM schema_info WHERE key='version'").fetchone()[0] == "2"
    assert c2.execute("SELECT name FROM sqlite_master WHERE name='identity_matches'").fetchone()
    c2.close()


def test_unknown_schema_still_refused(tmp_path):
    path = tmp_path / "future.sqlite3"
    c = db.connect(path)
    c.execute("UPDATE schema_info SET value = '99' WHERE key = 'version'")
    c.commit()
    c.close()
    with pytest.raises(db.CatalogueError):
        db.connect(path)
