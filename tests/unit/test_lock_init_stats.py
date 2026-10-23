"""Scan lock, abandoned scans, init and stats."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

import tabarc_media.inspection.runner as runner
from tabarc_media.catalogue.db import CatalogueError, ScanLock, connect
from tabarc_media.catalogue.stats import collect, human_size
from tabarc_media.cli.main import EXIT_CONFIG, EXIT_OK, main
from tabarc_media.config.loader import (
    ConfigError,
    default_config_text,
    load_config,
    write_initial_config,
)
from tests.conftest import write_config


# ------------------------------------------------------------------ lock

def test_second_lock_is_refused(tmp_path):
    db = tmp_path / "c.sqlite3"
    with ScanLock(db):
        with pytest.raises(CatalogueError, match="Another scan"):
            with ScanLock(db):
                pass


def test_lock_released_after_exit(tmp_path):
    db = tmp_path / "c.sqlite3"
    with ScanLock(db):
        pass
    with ScanLock(db):   # must not raise
        pass


def test_lock_released_after_error(tmp_path):
    db = tmp_path / "c.sqlite3"
    with pytest.raises(RuntimeError):
        with ScanLock(db):
            raise RuntimeError("boom")
    with ScanLock(db):
        pass


def test_leftover_lock_file_does_not_block(tmp_path):
    # A crashed run leaves the file behind. The lock itself dies with the process.
    db = tmp_path / "c.sqlite3"
    (tmp_path / "c.sqlite3.lock").write_text("stale")
    with ScanLock(db):
        pass


def test_cli_refuses_while_scan_running(tmp_path, library, monkeypatch, capsys):
    db = tmp_path / "local" / "c.sqlite3"
    cfg = write_config(tmp_path / "c.toml", db, [library])
    monkeypatch.setattr("tabarc_media.cli.main.ffprobe_available", lambda: False)
    with ScanLock(db):
        assert main(["--config", str(cfg), "inventory", "--quiet"]) == EXIT_CONFIG
    assert "Another scan" in capsys.readouterr().err
    # Nothing was written by the refused run.
    assert not db.exists() or sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM scan_jobs").fetchone()[0] == 0


# ------------------------------------------------------- abandoned scans

def test_stale_running_scan_marked_abandoned(tmp_path, library):
    cfg_path = write_config(tmp_path / "c.toml", tmp_path / "local" / "c.sqlite3", [library])
    cfg = load_config(cfg_path)
    conn = connect(cfg.database_path)
    conn.execute("INSERT INTO scan_jobs (started_at, status, roots_json) "
                 "VALUES ('2026-01-01T00:00:00+00:00', 'running', '[]')")
    conn.commit()
    s = runner.run_inventory(conn, cfg, probe=False)
    rows = conn.execute("SELECT id, status, finished_at FROM scan_jobs ORDER BY id").fetchall()
    conn.close()
    assert s.abandoned_before == 1
    assert (rows[0]["status"], rows[0]["finished_at"] is not None) == ("abandoned", True)
    assert rows[1]["status"] == "complete"


def test_abandoned_reported_in_output(tmp_path, library, monkeypatch, capsys):
    db = tmp_path / "local" / "c.sqlite3"
    cfg = write_config(tmp_path / "c.toml", db, [library])
    conn = connect(db)
    conn.execute("INSERT INTO scan_jobs (started_at, status, roots_json) "
                 "VALUES ('2026-01-01T00:00:00+00:00', 'running', '[]')")
    conn.commit()
    conn.close()
    monkeypatch.setattr("tabarc_media.cli.main.ffprobe_available", lambda: False)
    main(["--config", str(cfg), "inventory", "--quiet"])
    assert "marked abandoned: 1" in capsys.readouterr().out


# ------------------------------------------------------------------ init

def test_packaged_default_is_readable():
    text = default_config_text()
    assert "[database]" in text and "\nroots = []\n" in text


def test_init_writes_a_loadable_config(tmp_path):
    target = tmp_path / "cfg" / "config.toml"
    # Database path in the packaged default uses ~, which is fine to load.
    cfg = write_initial_config(target, ["/mnt/nas/Movies", "/mnt/nas/TV"])
    assert target.is_file()
    assert [str(r) for r in cfg.roots] == ["/mnt/nas/Movies", "/mnt/nas/TV"]
    assert [str(r) for r in load_config(target).roots] == ["/mnt/nas/Movies", "/mnt/nas/TV"]
    assert not list(target.parent.glob("*.tmp"))


def test_init_without_roots(tmp_path):
    cfg = write_initial_config(tmp_path / "config.toml", [])
    assert cfg.roots == ()


def test_init_never_overwrites(tmp_path):
    target = tmp_path / "config.toml"
    target.write_text("# mine\n")
    with pytest.raises(ConfigError, match="not overwriting"):
        write_initial_config(target, ["/mnt/a"])
    assert target.read_text() == "# mine\n"


@pytest.mark.parametrize("roots", [["relative/path"], ["/mnt/a", "/mnt/a"], ["/mnt/a", "/mnt/a/b"]])
def test_init_bad_roots_leave_nothing_behind(tmp_path, roots):
    target = tmp_path / "config.toml"
    with pytest.raises(ConfigError):
        write_initial_config(target, roots)
    assert list(tmp_path.iterdir()) == []


def test_init_handles_awkward_paths(tmp_path):
    odd = '/mnt/My "Films" \\ new'
    cfg = write_initial_config(tmp_path / "c.toml", [odd])
    assert str(cfg.roots[0]) == odd


def test_init_command(tmp_path, capsys):
    target = tmp_path / "config.toml"
    assert main(["--config", str(target), "init", "--roots", "/mnt/nas/Movies"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Wrote" in out and "/mnt/nas/Movies" in out
    assert main(["--config", str(target), "init"]) == EXIT_CONFIG   # second time: refused
    assert "not overwriting" in capsys.readouterr().err


# ----------------------------------------------------------------- stats

def test_human_size():
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1024) == "1.00 KiB"
    assert human_size(1024 ** 4) == "1.00 TiB"
    assert human_size(41 * 1024 ** 4) == "41.00 TiB"
    assert human_size(5000 * 1024 ** 4) == "5000.00 TiB"   # no unit beyond TiB


def _scan(tmp_path, library):
    db = tmp_path / "local" / "c.sqlite3"
    cfg_path = write_config(tmp_path / "c.toml", db, [library])
    cfg = load_config(cfg_path)
    conn = connect(db)
    runner.run_inventory(conn, cfg, probe=False)
    return conn, cfg, cfg_path


def test_collect_counts_and_bytes(tmp_path, library):
    conn, cfg, _ = _scan(tmp_path, library)
    st = collect(conn, cfg.roots)
    conn.close()
    (root,) = st.roots
    assert (root.present, root.missing) == (3, 0)
    assert root.present_bytes == 10 + 8 + 5      # mkv, nfo "<movie/>", epub
    assert root.by_kind == {"book": 1, "sidecar": 1, "video": 1}
    assert st.videos_not_probed == 1 and st.videos_probed_ok == 0
    assert st.last_scan["status"] == "complete"


def test_collect_excludes_missing_from_bytes(tmp_path, library):
    conn, cfg, _ = _scan(tmp_path, library)
    (library / "Books" / "Author" / "Title.epub").unlink()
    runner.run_inventory(conn, cfg, probe=False)
    st = collect(conn, cfg.roots)
    conn.close()
    (root,) = st.roots
    assert (root.present, root.missing) == (2, 1)
    assert root.present_bytes == 10 + 8


def test_collect_shows_roots_dropped_from_config(tmp_path, library):
    conn, cfg, _ = _scan(tmp_path, library)
    st = collect(conn, ())
    conn.close()
    assert [(r.root, r.configured) for r in st.roots] == [(str(library), False)]


def test_stats_command(tmp_path, library, capsys):
    _, _, cfg_path = (lambda t: (t[0].close(), t[1], t[2]))(_scan(tmp_path, library))
    assert main(["--config", str(cfg_path), "stats"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Total present: 3 files" in out
    assert "video" in out and "book" in out
    assert "Video probes: 0 ok, 0 failed, 1 not probed" in out


def test_stats_without_catalogue(tmp_path, library, capsys):
    cfg = write_config(tmp_path / "c.toml", tmp_path / "local" / "none.sqlite3", [library])
    assert main(["--config", str(cfg), "stats"]) == EXIT_CONFIG
    assert "Run 'tabarc-media inventory' first" in capsys.readouterr().out
    assert not (tmp_path / "local" / "none.sqlite3").exists()   # stats must not create it


def test_stats_does_not_modify_catalogue(tmp_path, library):
    conn, cfg, cfg_path = _scan(tmp_path, library)
    conn.close()
    db = cfg.database_path
    before = shutil.copy(db, tmp_path / "before.sqlite3")
    rows_before = sqlite3.connect(before).execute("SELECT * FROM media_files ORDER BY id").fetchall()
    main(["--config", str(cfg_path), "stats"])
    rows_after = sqlite3.connect(db).execute("SELECT * FROM media_files ORDER BY id").fetchall()
    assert rows_before == rows_after
