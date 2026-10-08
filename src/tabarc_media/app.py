"""Local HTTP interface. No media-modifying endpoints exist in this release."""

import argparse
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .catalogue import Catalogue
from .scanner import Scanner

ASSETS = Path(__file__).resolve().parent / "static"


class LibraryInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    root: str = Field(min_length=1)
    media_types: list[str] = Field(min_length=1)
    applications: list[str] = Field(default_factory=list)
    scan_profile: str = "balanced"


def suggestions(files: list[dict]):
    """Never authoritative: these are filename guesses, not provider matches."""
    output = []
    episode = re.compile(r"(?i)^(.*?)\bS(\d{1,2})E(\d{1,3})(?:E\d{1,3})?\b")
    movie = re.compile(r"(?i)^(.*?)\b((?:19|20)\d{2})\b")

    for file in files:
        path = Path(file["relative_path"])
        if file["kind"] != "film":
            continue
        title = None
        match = episode.search(path.stem)
        if match:
            name = re.sub(r"[._]+", " ", match.group(1)).strip(" -")
            if name:
                title = f"{name} - S{int(match.group(2)):02d}E{int(match.group(3)):02d}{path.suffix}"
        else:
            match = movie.search(path.stem)
            if match:
                name = re.sub(r"[._]+", " ", match.group(1)).strip(" -")
                if name:
                    title = f"{name} ({match.group(2)}){path.suffix}"
        if title and title != path.name:
            output.append({
                "current": file["relative_path"],
                "suggested_name": title,
                "status": "review_required",
                "reason": "Filename pattern only. Verify identity, edition and associated files before renaming."
            })
    return output


def create_app(data_dir: Path | None = None):
    if data_dir is None:
        data_dir = Path(os.environ.get(
            "TABARC_DATA_DIR", "~/.local/share/tabarc-media-organiser"
        )).expanduser()
    store = Catalogue(Path(data_dir))
    scanner = Scanner(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        scanner.shutdown()

    app = FastAPI(title="TABARC Media Organiser", version="0.1.0-alpha",
                  docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.catalogue = store
    app.state.scanner = scanner

    @app.middleware("http")
    async def local_write_protection(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-tabarc-local") != "1":
                return JSONResponse(status_code=403, content={"detail": "Local action header required."})
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
                    return JSONResponse(status_code=403, content={"detail": "Unexpected request origin."})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")

    @app.get("/")
    def home():
        return FileResponse(ASSETS / "index.html")

    @app.get("/api/status")
    def status():
        return store.status()

    @app.get("/api/libraries")
    def list_libraries():
        return store.libraries()

    @app.post("/api/libraries", status_code=201)
    def add_library(payload: LibraryInput):
        try:
            lib_id = store.add_library(payload.name, Path(payload.root),
                                       payload.media_types, payload.applications,
                                       payload.scan_profile)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return store.library(lib_id)

    @app.get("/api/libraries/{library_id}/files")
    def list_files(library_id: int, limit: int = Query(100, ge=1, le=500),
                   search: str = Query("", max_length=200)):
        if not store.library(library_id):
            raise HTTPException(404, "Library not found.")
        return store.files(library_id, limit, search)

    @app.get("/api/libraries/{library_id}/proposals")
    def preview(library_id: int, limit: int = Query(100, ge=1, le=500)):
        if not store.library(library_id):
            raise HTTPException(404, "Library not found.")
        return {"mode": "preview_only", "proposals": suggestions(store.files(library_id, limit))}

    @app.post("/api/libraries/{library_id}/scan", status_code=202)
    def start_scan(library_id: int):
        try:
            job_id = scanner.start(library_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.job(job_id)

    @app.get("/api/jobs")
    def list_jobs():
        return store.jobs()

    @app.post("/api/jobs/{job_id}/pause", status_code=202)
    def pause_job(job_id: int):
        try:
            scanner.pause(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"message": "Pause requested.", "job_id": job_id}

    @app.post("/api/jobs/{job_id}/resume", status_code=202)
    def resume_job(job_id: int):
        job = store.job(job_id)
        if not job:
            raise HTTPException(404, "Job not found.")
        try:
            scanner.start(job["library_id"], resume_id=job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return store.job(job_id)

    return app


def main():
    parser = argparse.ArgumentParser(description="Read-only local media catalogue")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1–65535")

    import uvicorn
    app = create_app(args.data_dir)
    # Remote binding isn't an option in the initial release. Anyone who wants
    # a LAN service will need authentication and a proper transport layer first.
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
