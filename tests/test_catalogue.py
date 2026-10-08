from pathlib import Path

import pytest

from tabarc_media.catalogue import Catalogue, classify


def test_classification():
    assert classify("example.MKV") == "film"
    assert classify("manual.EPUB") == "ebook"
    assert classify("photo.NEF") == "photo"
    assert classify("notes.unknown") == "other"


def test_catalogue_persists_and_filters(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    store = Catalogue(tmp_path / "state")
    number = store.add_library("Collection", root, ["films", "ebooks"],
                               ["plex", "jellyfin"], "quiet")
    assert store.library(number)["scan_profile"] == "quiet"
    store.upsert_batch(number, [
        ("Film_100%.mkv", "film", 125, 500, 10.0),
        ("Books/manual.epub", "ebook", 25, 600, 10.0),
    ])
    assert len(store.files(number)) == 2
    assert [x["relative_path"] for x in store.files(number, search="100%")] == ["Film_100%.mkv"]
    assert [x["relative_path"] for x in store.files(number, search="Film_")] == ["Film_100%.mkv"]
    assert store.status()["files"] == 2

    reloaded = Catalogue(tmp_path / "state")
    assert reloaded.status()["files"] == 2
    assert reloaded.library(number)["applications"] == ["jellyfin", "plex"]


def test_invalid_and_overlapping_roots(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    subdir = root / "shows"
    subdir.mkdir()
    store = Catalogue(tmp_path / "db")
    store.add_library("A", root, ["films"], [])
    with pytest.raises(ValueError, match="Overlapping"):
        store.add_library("B", subdir, ["films"], [])
    with pytest.raises(ValueError, match="profile"):
        store.add_library("C", subdir, ["films"], [], "ultra")
    with pytest.raises(ValueError, match="catalogue directory"):
        store.add_library("D", tmp_path, ["films"], [])
    with pytest.raises(ValueError, match="media type"):
        store.add_library("E", subdir, ["pretend"], [])


def test_interrupted_job_becomes_paused(tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    data = tmp_path / "state"
    store = Catalogue(data)
    lib = store.add_library("Films", root, ["films"], [])
    job = store.new_job(lib)
    restarted = Catalogue(data)
    assert restarted.job(job)["state"] == "paused"
