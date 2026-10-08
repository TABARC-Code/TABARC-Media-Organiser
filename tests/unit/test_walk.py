from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tabarc_media.config.loader import default_inventory
from tabarc_media.inspection.inventory import (
    FileRecord,
    ScanIssue,
    media_kind_for,
    probe_video,
    walk_root,
)

INV = default_inventory()


def _records(root):
    return [i for i in walk_root(root, INV) if isinstance(i, FileRecord)]


def _issues(root):
    return [i for i in walk_root(root, INV) if isinstance(i, ScanIssue)]


def _snapshot(root: Path):
    return sorted(
        (str(p.relative_to(root)), p.lstat().st_size, p.lstat().st_mtime_ns)
        for p in root.rglob("*")
    )


def test_media_kind_mapping():
    assert media_kind_for(".MKV") == "video"
    assert media_kind_for(".m2ts") == "video"
    assert media_kind_for(".epub") == "book"
    assert media_kind_for(".flac") == "audio"
    assert media_kind_for(".cbz") == "comic"
    assert media_kind_for(".xyz") == "other"


def test_finds_media_and_sidecars_only(library):
    found = {(r.rel_path, r.media_kind) for r in _records(library)}
    assert found == {
        ("Movies/Arrival (2016)/Arrival (2016).mkv", "video"),
        ("Movies/Arrival (2016)/movie.nfo", "sidecar"),
        ("Books/Author/Title.epub", "book"),
    }


def test_skips_review_snapshot_and_appledouble(library):
    rels = {r.rel_path for r in _records(library)}
    assert not any(r.startswith("_review") for r in rels)
    assert not any("#snapshot" in r for r in rels)
    assert not any(Path(r).name.startswith("._") for r in rels)


def test_exclusion_is_case_insensitive(tmp_path):
    (tmp_path / "$Recycle.Bin").mkdir()
    (tmp_path / "$Recycle.Bin" / "old.mkv").write_bytes(b"x")
    (tmp_path / "keep.mkv").write_bytes(b"x")
    assert [r.rel_path for r in _records(tmp_path)] == ["keep.mkv"]


def test_order_is_stable(library):
    first = [r.rel_path for r in _records(library)]
    assert first == [r.rel_path for r in _records(library)]
    assert first == sorted(first)


def test_walk_does_not_modify_library(library):
    before = _snapshot(library)
    list(walk_root(library, INV))
    assert _snapshot(library) == before


def test_does_not_follow_symlinks(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    (library / "real.mkv").write_bytes(b"x")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.mkv").write_bytes(b"w")
    os.symlink(outside, library / "linkdir", target_is_directory=True)
    os.symlink(outside / "hidden.mkv", library / "linkfile.mkv")
    assert [r.rel_path for r in _records(library)] == ["real.mkv"]


def test_missing_root_is_an_issue_not_a_crash(tmp_path):
    issues = _issues(tmp_path / "not-mounted")
    assert [i.kind for i in issues] == ["root_missing"]


def test_empty_root_is_flagged(tmp_path):
    (tmp_path / "mnt").mkdir()
    assert [i.kind for i in _issues(tmp_path / "mnt")] == ["root_empty"]


def test_relative_root_refused():
    with pytest.raises(ValueError):
        list(walk_root(Path("relative"), INV))


def test_unreadable_directory_is_reported(library, monkeypatch):
    # Tests run as root in CI, where chmod is ignored, so fake the error.
    target = str(library / "Books")
    real_scandir = os.scandir

    def fake_scandir(path):
        if str(path) == target:
            raise PermissionError(13, "Permission denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    items = list(walk_root(library, INV))
    issues = [i for i in items if isinstance(i, ScanIssue)]
    assert [(i.kind, i.rel_path) for i in issues] == [("dir_unreadable", "Books")]
    # The rest of the library is still scanned.
    assert any(isinstance(i, FileRecord) and i.media_kind == "video" for i in items)


@pytest.mark.skipif(sys.platform != "linux", reason="needs a byte-transparent filesystem")
def test_undecodable_filename_recorded_and_flagged(tmp_path):
    raw_name = b"caf\xe9.mkv"   # Latin-1, not valid UTF-8
    try:
        (tmp_path / os.fsdecode(raw_name)).write_bytes(b"x")
    except OSError:
        pytest.skip("filesystem rejects non-UTF-8 names")
    items = list(walk_root(tmp_path, INV))
    rec = next(i for i in items if isinstance(i, FileRecord))
    assert rec.rel_path_raw == raw_name
    assert rec.name_decodable is False
    assert rec.rel_path == "caf\\xe9.mkv"
    # The walker records it; the runner flags it (once). See test_inventory_run.
    assert not any(isinstance(i, ScanIssue) for i in items)
    assert os.path.exists(rec.abs_path)


def test_probe_video_refuses_relative_path():
    with pytest.raises(ValueError):
        probe_video("-i.mkv", 5)
