import sys
import types
import warnings

import pytest

from tabarc_media.catalogue import db


def test_no_lock_backend_refuses_to_scan(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_lock_backend", lambda: None)
    with pytest.raises(db.CatalogueError, match="two scans could run"):
        with db.ScanLock(tmp_path / "c.sqlite3"):
            pass


def test_msvcrt_backend_locks_and_unlocks(monkeypatch, tmp_path):
    calls = []
    fake = types.SimpleNamespace(
        LK_NBLCK=2, LK_UNLCK=0,
        locking=lambda fd, mode, n: calls.append(mode),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(db, "_lock_backend", lambda: "msvcrt")
    with db.ScanLock(tmp_path / "c.sqlite3"):
        assert calls == [2]
    assert calls == [2, 0]


def test_locked_by_another_process_is_reported(monkeypatch, tmp_path):
    def busy(fd, mode, n):
        raise OSError("locked")

    fake = types.SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=busy)
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(db, "_lock_backend", lambda: "msvcrt")
    with pytest.raises(db.CatalogueError, match="Another scan"):
        with db.ScanLock(tmp_path / "c.sqlite3"):
            pass


def test_macos_mount_table_parsed_by_longest_prefix(tmp_path):
    share = tmp_path / "share"
    films = share / "Films"
    films.mkdir(parents=True)
    table = (
        "/dev/disk3s1 on / (apfs, local, journaled)\n"
        f"//user@nas/media on {share} (smbfs, nodev, nosuid, mounted by me)\n"
        f"//user@nas/films on {films} (smbfs, nodev)\n"
        "garbage line\n"
    )
    assert db._fs_type_from_macos_mount(films / "Some Film", table) == "smbfs"
    assert db._fs_type_from_macos_mount(share / "TV", table) == "smbfs"
    assert db._fs_type_from_macos_mount(tmp_path / "elsewhere", table) == "apfs"


def test_linux_mount_table_longest_prefix(tmp_path):
    nas = tmp_path / "nas"
    (nas / "Films").mkdir(parents=True)
    table = f"/dev/sda1 / ext4 rw 0 0\nnas:/share {nas} nfs4 rw 0 0\n"
    assert db._fs_type_from_mounts(nas / "Films", table) == "nfs4"
    assert db._fs_type_from_mounts(tmp_path, table) == "ext4"


def test_unknown_filesystem_warns_rather_than_passing_silently(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "filesystem_type", lambda path: None)
    with pytest.warns(UserWarning, match="network-storage check was skipped"):
        conn = db.connect(tmp_path / "c.sqlite3")
    conn.close()


def test_known_local_filesystem_does_not_warn(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "filesystem_type", lambda path: "ext4")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        conn = db.connect(tmp_path / "c.sqlite3")
    conn.close()


def test_windows_network_drive_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "filesystem_type", lambda path: "windows-network")
    with pytest.raises(db.CatalogueError, match="network filesystem"):
        db.connect(tmp_path / "c.sqlite3")


def test_config_path_can_be_set_from_environment(monkeypatch):
    import importlib
    from tabarc_media.cli import main as cli

    monkeypatch.setenv("TABARC_CONFIG", "/config/config.toml")
    importlib.reload(cli)
    try:
        assert str(cli.DEFAULT_CONFIG) == "/config/config.toml"
    finally:
        monkeypatch.delenv("TABARC_CONFIG")
        importlib.reload(cli)
