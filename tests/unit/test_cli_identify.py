from __future__ import annotations

from datetime import date


import tabarc_media.identity.runner as runner
from tabarc_media.catalogue.db import connect
from tabarc_media.cli.main import EXIT_CONFIG, EXIT_ISSUES, EXIT_OK, main
from tabarc_media.config.loader import load_config
from tabarc_media.identity.providers import Candidate, ProviderError
from tabarc_media.inspection.runner import run_inventory
from tests.conftest import write_config


class Fake:
    def __init__(self, name, results=(), error=False):
        self.name, self.results, self.error, self.calls = name, list(results), error, 0

    def search(self, title, limit=5):
        self.calls += 1
        if self.error:
            raise ProviderError(self.name, "down", transient=True)
        return list(self.results)


def cand(title, year, kind, pid="Q1", provider="wikidata"):
    return Candidate(provider=provider, provider_id=pid, title=title, year=year, kind=kind,
                     original_title=None, language="en-gb", source_url=None,
                     retrieved_on=date(2026, 10, 24), licence="CC0 1.0")


def setup(tmp_path, library, providers_toml):
    cfg_path = write_config(tmp_path / "c.toml", tmp_path / "db" / "c.sqlite3", [library],
                            providers_toml)
    cfg = load_config(cfg_path)
    conn = connect(cfg.database_path)
    run_inventory(conn, cfg, probe=False)
    conn.close()
    return str(cfg_path), cfg


GOOD = '[providers]\ncontact = "ops@example.org"\n'


def patch(monkeypatch, **fakes):
    monkeypatch.setattr(runner, "build_providers",
                        lambda cfg, client=None: {n: runner.Memo(f) for n, f in fakes.items()})


def test_identify_refuses_without_a_contact(tmp_path, library, capsys):
    path, _ = setup(tmp_path, library, "")
    assert main(["--config", path, "identify"]) == EXIT_CONFIG
    assert "contact" in capsys.readouterr().err


def test_offline_makes_no_lookups(tmp_path, library, monkeypatch, capsys):
    path, _ = setup(tmp_path, library, GOOD + "offline = true\n")

    def boom(*a, **k):
        raise AssertionError("providers must not be built while offline")

    monkeypatch.setattr(runner, "build_providers", boom)
    assert main(["--config", path, "identify"]) == EXIT_OK
    assert "Offline mode" in capsys.readouterr().out


def test_identify_then_review_then_accept(tmp_path, library, monkeypatch, capsys):
    path, cfg = setup(tmp_path, library, GOOD)
    patch(monkeypatch, wikidata=Fake("wikidata", [cand("Arrival", 2016, "film"),
                                                   cand("Arrival", 1999, "film", pid="Q2")]),
          tvmaze=Fake("tvmaze"), openlibrary=Fake("openlibrary", [cand("Title", None, "book",
                                                                       pid="/works/OL1W",
                                                                       provider="openlibrary")]))
    assert main(["--config", path, "identify"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "matched" in out and "pending" in out

    assert main(["--config", path, "review", "list"]) == EXIT_OK
    listing = capsys.readouterr().out
    assert "Title.epub" in listing and "1." in listing

    conn = connect(cfg.database_path)
    rid = conn.execute("SELECT id FROM identity_matches WHERE rel_path LIKE '%Title.epub'"
                       ).fetchone()["id"]
    conn.close()

    assert main(["--config", path, "review", "accept", str(rid), "--candidate", "9"]) == EXIT_CONFIG
    capsys.readouterr()
    assert main(["--config", path, "review", "accept", str(rid), "--candidate", "1"]) == EXIT_OK
    assert "No files were changed" in capsys.readouterr().out

    conn = connect(cfg.database_path)
    row = conn.execute("SELECT status, chosen_id FROM identity_matches WHERE id = ?",
                       (rid,)).fetchone()
    conn.close()
    assert (row["status"], row["chosen_id"]) == ("accepted", "/works/OL1W")


def test_reject_and_unknown_ids(tmp_path, library, monkeypatch, capsys):
    path, cfg = setup(tmp_path, library, GOOD)
    patch(monkeypatch, wikidata=Fake("wikidata"), tvmaze=Fake("tvmaze"),
          openlibrary=Fake("openlibrary"))
    main(["--config", path, "identify"])
    capsys.readouterr()
    conn = connect(cfg.database_path)
    rid = conn.execute("SELECT id FROM identity_matches LIMIT 1").fetchone()["id"]
    conn.close()
    assert main(["--config", path, "review", "reject", str(rid)]) == EXIT_OK
    assert main(["--config", path, "review", "reject", "9999"]) == EXIT_CONFIG
    assert main(["--config", path, "review", "accept", "9999", "--candidate", "1"]) == EXIT_CONFIG


def test_provider_failure_gives_exit_3(tmp_path, library, monkeypatch, capsys):
    path, _ = setup(tmp_path, library, GOOD)
    patch(monkeypatch, wikidata=Fake("wikidata", error=True), tvmaze=Fake("tvmaze", error=True),
          openlibrary=Fake("openlibrary", error=True))
    assert main(["--config", path, "identify"]) == EXIT_ISSUES


def test_about_lists_credits_and_marks_disabled_sources(tmp_path, library, capsys):
    path, _ = setup(tmp_path, library, GOOD + 'enabled = ["wikidata"]\n')
    assert main(["--config", path, "about"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "MIT licence" in out
    assert "[enabled ] Wikidata" in out
    assert "[disabled] TV data from TVmaze" in out and "CC BY-SA 4.0" in out
