"""End-to-end inventory runs against throwaway libraries."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

import tabarc_media.inspection.runner as runner
from tabarc_media.catalogue.db import connect
from tabarc_media.cli.main import EXIT_INTERRUPTED, EXIT_ISSUES, EXIT_OK, main
from tabarc_media.config.loader import load_config
from tests.conftest import write_config


class FakeProbe:
    """Counts calls; can be told to fail or interrupt."""

    def __init__(self, result=None, raise_exc=None):
        self.calls = 0
        self.result = result if result is not None else {"format": {"duration": "1.0"}}
        self.raise_exc = raise_exc

    def __call__(self, path, timeout):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        return self.result


@pytest.fixture
def setup(tmp_path, library):
    db_path = tmp_path / "local" / "catalogue.sqlite3"
    cfg_path = write_config(tmp_path / "config.toml", db_path, [library])
    return library, db_path, cfg_path


def _run(cfg_path, monkeypatch, probe=None, *args):
    monkeypatch.setattr(runner, "probe_video", probe or FakeProbe())
    monkeypatch.setattr("tabarc_media.cli.main.ffprobe_available", lambda: True)
    return main(["--config", str(cfg_path), "inventory", "--quiet", *args])


def _q(db_path, sql, *params):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_end_to_end(setup, monkeypatch):
    library, db_path, cfg_path = setup
    assert _run(cfg_path, monkeypatch) == EXIT_OK
    rows = _q(db_path, "SELECT rel_path, media_kind, present FROM media_files ORDER BY rel_path")
    assert rows == [
        ("Books/Author/Title.epub", "book", 1),
        ("Movies/Arrival (2016)/Arrival (2016).mkv", "video", 1),
        ("Movies/Arrival (2016)/movie.nfo", "sidecar", 1),
    ]
    assert _q(db_path, "SELECT status, files_seen, files_new FROM scan_jobs") == [
        ("complete", 3, 3)
    ]


def test_rerun_is_idempotent_and_skips_probe(setup, monkeypatch):
    _, db_path, cfg_path = setup
    probe = FakeProbe()
    _run(cfg_path, monkeypatch, probe)
    _run(cfg_path, monkeypatch, probe)
    assert probe.calls == 1    # one video, probed once across two runs
    assert _q(db_path, "SELECT COUNT(*) FROM media_files") == [(3,)]
    assert _q(db_path, "SELECT files_unchanged FROM scan_jobs ORDER BY id")[-1] == (3,)


def test_changed_file_is_reprobed(setup, monkeypatch):
    library, db_path, cfg_path = setup
    probe = FakeProbe()
    _run(cfg_path, monkeypatch, probe)
    (library / "Movies" / "Arrival (2016)" / "Arrival (2016).mkv").write_bytes(b"new" * 50)
    _run(cfg_path, monkeypatch, probe)
    assert probe.calls == 2
    assert _q(db_path, "SELECT files_changed FROM scan_jobs ORDER BY id")[-1] == (1,)


def test_transient_probe_failure_is_retried(setup, monkeypatch):
    _, db_path, cfg_path = setup
    _run(cfg_path, monkeypatch,
         FakeProbe(result={"error": "timeout after 30s", "transient": True}))
    assert _q(db_path, "SELECT probe_ok FROM media_files WHERE media_kind='video'") == [(0,)]
    ok = FakeProbe()
    _run(cfg_path, monkeypatch, ok)
    assert ok.calls == 1
    assert _q(db_path, "SELECT probe_ok FROM media_files WHERE media_kind='video'") == [(1,)]


def test_permanent_probe_failure_not_retried_until_file_changes(setup, monkeypatch):
    library, db_path, cfg_path = setup
    bad = FakeProbe(result={"error": "Invalid data found", "transient": False})
    assert _run(cfg_path, monkeypatch, bad) == EXIT_ISSUES
    assert _q(db_path, "SELECT kind FROM scan_issues") == [("probe_failed",)]
    # Second scan: no re-probe, no repeated issue, clean exit.
    assert _run(cfg_path, monkeypatch, bad) == EXIT_OK
    assert bad.calls == 1
    # File replaced: probe again.
    (library / "Movies" / "Arrival (2016)" / "Arrival (2016).mkv").write_bytes(b"fixed" * 9)
    _run(cfg_path, monkeypatch, bad)
    assert bad.calls == 2


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="byte-transparent fs")
def test_undecodable_name_flagged_once(tmp_path, monkeypatch):
    import os
    lib = tmp_path / "lib"
    lib.mkdir()
    try:
        (lib / os.fsdecode(b"caf\xe9.mkv")).write_bytes(b"x")
    except OSError:
        pytest.skip("filesystem rejects non-UTF-8 names")
    db_path = tmp_path / "local" / "c.sqlite3"
    cfg_path = write_config(tmp_path / "c.toml", db_path, [lib])
    assert _run(cfg_path, monkeypatch) == EXIT_ISSUES
    assert _run(cfg_path, monkeypatch) == EXIT_OK
    assert _q(db_path, "SELECT scan_id, kind FROM scan_issues") == [(1, "undecodable_name")]
    assert _q(db_path, "SELECT rel_path_raw FROM media_files") == [(b"caf\xe9.mkv",)]


def test_no_probe_flag(setup, monkeypatch):
    _, db_path, cfg_path = setup
    probe = FakeProbe()
    _run(cfg_path, monkeypatch, probe, "--no-probe")
    assert probe.calls == 0
    assert _q(db_path, "SELECT probe_json FROM media_files WHERE media_kind='video'") == [(None,)]


def test_removed_file_marked_missing_not_deleted(setup, monkeypatch):
    library, db_path, cfg_path = setup
    _run(cfg_path, monkeypatch)
    # Removing a fixture file in tmp_path, not real media.
    (library / "Books" / "Author" / "Title.epub").unlink()
    assert _run(cfg_path, monkeypatch) == EXIT_OK
    assert _q(db_path, "SELECT present FROM media_files WHERE rel_path LIKE 'Books/%'") == [(0,)]
    assert _q(db_path, "SELECT COUNT(*) FROM media_files") == [(3,)]


def test_returning_file_marked_present_again(setup, monkeypatch):
    library, db_path, cfg_path = setup
    book = library / "Books" / "Author" / "Title.epub"
    _run(cfg_path, monkeypatch)
    data = book.read_bytes()
    book.unlink()
    _run(cfg_path, monkeypatch)
    book.write_bytes(data)
    _run(cfg_path, monkeypatch)
    assert _q(db_path, "SELECT present FROM media_files WHERE rel_path LIKE 'Books/%'") == [(1,)]


def test_unmounted_share_does_not_mark_everything_missing(setup, monkeypatch):
    library, db_path, cfg_path = setup
    _run(cfg_path, monkeypatch)
    # Simulate an unmounted share: the mount point is left empty.
    shutil.rmtree(library)
    library.mkdir()
    assert _run(cfg_path, monkeypatch) == EXIT_ISSUES
    assert _q(db_path, "SELECT COUNT(*) FROM media_files WHERE present = 0") == [(0,)]
    assert _q(db_path, "SELECT kind FROM scan_issues") == [("root_empty",)]


def test_unreadable_folder_blocks_missing_check(setup, monkeypatch):
    import os
    library, db_path, cfg_path = setup
    _run(cfg_path, monkeypatch)
    target = str(library / "Books")
    real_scandir = os.scandir

    def fake_scandir(path):
        if str(path) == target:
            raise PermissionError(13, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    assert _run(cfg_path, monkeypatch) == EXIT_ISSUES
    # The book wasn't seen, but must not be marked missing.
    assert _q(db_path, "SELECT present FROM media_files WHERE rel_path LIKE 'Books/%'") == [(1,)]


def test_interrupt_is_recorded(setup, monkeypatch):
    _, db_path, cfg_path = setup
    code = _run(cfg_path, monkeypatch, FakeProbe(raise_exc=KeyboardInterrupt()))
    assert code == EXIT_INTERRUPTED
    status, finished = _q(db_path, "SELECT status, finished_at FROM scan_jobs")[0]
    assert status == "interrupted" and finished is not None


def test_unexpected_error_recorded_then_raised(setup, monkeypatch):
    _, db_path, cfg_path = setup
    with pytest.raises(RuntimeError):
        _run(cfg_path, monkeypatch, FakeProbe(raise_exc=RuntimeError("boom")))
    assert _q(db_path, "SELECT status FROM scan_jobs") == [("failed",)]


def test_missing_ffprobe_warns_and_continues(setup, monkeypatch, capsys):
    _, db_path, cfg_path = setup
    monkeypatch.setattr("tabarc_media.cli.main.ffprobe_available", lambda: False)
    probe = FakeProbe()
    monkeypatch.setattr(runner, "probe_video", probe)
    assert main(["--config", str(cfg_path), "inventory", "--quiet"]) == EXIT_OK
    assert probe.calls == 0
    assert "ffprobe not found" in capsys.readouterr().err


def test_issues_command(setup, monkeypatch, capsys):
    library, db_path, cfg_path = setup
    shutil.rmtree(library)
    library.mkdir()
    _run(cfg_path, monkeypatch)
    capsys.readouterr()
    assert main(["--config", str(cfg_path), "issues"]) == EXIT_OK
    assert "root_empty" in capsys.readouterr().out


def test_no_roots_configured(tmp_path, capsys):
    cfg = write_config(tmp_path / "c.toml", tmp_path / "db.sqlite3", [])
    assert main(["--config", str(cfg), "inventory"]) == 2
    assert "No library roots" in capsys.readouterr().err


def test_bad_config_exit_code(tmp_path, capsys):
    cfg = tmp_path / "c.toml"
    cfg.write_text("[database\n")
    assert main(["--config", str(cfg), "inventory"]) == 2


def test_media_untouched_by_full_run(setup, monkeypatch):
    library, _, cfg_path = setup
    before = sorted((str(p), p.lstat().st_size, p.lstat().st_mtime_ns) for p in library.rglob("*"))
    _run(cfg_path, monkeypatch)
    after = sorted((str(p), p.lstat().st_size, p.lstat().st_mtime_ns) for p in library.rglob("*"))
    assert before == after


def test_run_inventory_direct(setup):
    _, db_path, cfg_path = setup
    cfg = load_config(cfg_path)
    conn = connect(cfg.database_path)
    try:
        s = runner.run_inventory(conn, cfg, probe=False)
    finally:
        conn.close()
    assert (s.status, s.files_seen, s.issues) == ("complete", 3, 0)
