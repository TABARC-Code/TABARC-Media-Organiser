from __future__ import annotations


import pytest

import tabarc_media.catalogue.db as db
from tabarc_media.catalogue.db import CatalogueError, connect, filesystem_type


def test_connect_creates_schema(tmp_path):
    conn = connect(tmp_path / "x.sqlite3")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"media_files", "scan_jobs", "scan_issues", "schema_info"} <= tables


def test_connect_twice_is_fine(tmp_path):
    connect(tmp_path / "x.sqlite3").close()
    connect(tmp_path / "x.sqlite3").close()


def test_schema_version_mismatch_refused(tmp_path):
    path = tmp_path / "x.sqlite3"
    conn = connect(path)
    conn.execute("UPDATE schema_info SET value = '99' WHERE key = 'version'")
    conn.commit()
    conn.close()
    with pytest.raises(CatalogueError, match="schema version"):
        connect(path)
    # And it must not have quietly rewritten the version.
    import sqlite3
    raw = sqlite3.connect(path)
    assert raw.execute("SELECT value FROM schema_info").fetchone()[0] == "99"
    raw.close()


def test_network_filesystem_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "filesystem_type", lambda p: "cifs")
    with pytest.raises(CatalogueError, match="network filesystem"):
        connect(tmp_path / "x.sqlite3")
    assert not (tmp_path / "x.sqlite3").exists()


def test_filesystem_type_picks_longest_mount(tmp_path):
    mounts = tmp_path / "mounts"
    nas = tmp_path / "nas share"
    nas.mkdir()
    escaped = str(nas).replace(" ", "\\040")
    mounts.write_text(
        "rootfs / ext4 rw 0 0\n"
        f"//nas/media {escaped} cifs rw 0 0\n"
    )
    assert filesystem_type(nas / "cat.sqlite3", mounts_file=mounts) == "cifs"
    assert filesystem_type(tmp_path / "elsewhere" / "c.sqlite3", mounts_file=mounts) == "ext4"


def test_filesystem_type_unknown_without_mount_table(tmp_path):
    assert filesystem_type(tmp_path, mounts_file=tmp_path / "nope") is None
