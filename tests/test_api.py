import time

from fastapi.testclient import TestClient

from tabarc_media.app import create_app, suggestions


HEADERS = {"X-Tabarc-Local": "1"}


def test_rejects_unapproved_and_cross_origin_requests(tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    with TestClient(create_app(tmp_path / "data")) as client:
        payload = {"name": "Films", "root": str(root), "media_types": ["films"],
                   "applications": ["plex", "jellyfin"], "scan_profile": "quiet"}
        assert client.post("/api/libraries", json=payload).status_code == 403
        assert client.post("/api/libraries", json=payload,
                           headers={**HEADERS, "Origin": "https://strange.example"}).status_code == 403
        result = client.post("/api/libraries", json=payload, headers=HEADERS)
        assert result.status_code == 201
        assert result.json()["scan_profile"] == "quiet"
        assert client.get("/api/status").json()["mode"] == "read-only"
        assert client.get("/").status_code == 200


def test_scan_and_preview_does_not_change_files(tmp_path):
    root = tmp_path / "films"
    root.mkdir()
    movie = root / "Arrival.2016.1080p.BluRay.mkv"
    movie.write_bytes(b"pretend video data")
    with TestClient(create_app(tmp_path / "data")) as client:
        response = client.post("/api/libraries", json={
            "name": "Movies", "root": str(root), "media_types": ["films"],
            "applications": ["plex"]
        }, headers=HEADERS)
        lib = response.json()["id"]
        job_response = client.post(f"/api/libraries/{lib}/scan", headers=HEADERS)
        assert job_response.status_code == 202
        job = job_response.json()["id"]

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = next(j for j in client.get("/api/jobs").json() if j["id"] == job)
            if result["state"] in {"completed", "failed"}:
                break
            time.sleep(.01)
        assert result["state"] == "completed"
        files = client.get(f"/api/libraries/{lib}/files").json()
        assert len(files) == 1
        proposals = client.get(f"/api/libraries/{lib}/proposals").json()
        assert proposals["mode"] == "preview_only"
        assert proposals["proposals"][0]["suggested_name"] == "Arrival (2016).mkv"
        assert movie.exists()
        assert movie.read_bytes() == b"pretend video data"
        assert not (root / "Arrival (2016).mkv").exists()


def test_unverified_suggestions_are_never_transactions():
    files = [
        {"relative_path": "Show.Name.S01E03.1080p.mkv", "kind": "film"},
        {"relative_path": "Something.2023.extended.mp4", "kind": "film"},
        {"relative_path": "NotATitle.mkv", "kind": "film"}
    ]
    proposals = suggestions(files)
    assert len(proposals) == 2
    assert all(p["status"] == "review_required" for p in proposals)
    assert proposals[0]["suggested_name"] == "Show Name - S01E03.mkv"
