"""SQLite catalogue. Media itself is never written by this module."""

import json
from contextlib import contextmanager
import sqlite3
import threading
import time
from pathlib import Path

KINDS = {
    "film": {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".webm", ".ts"},
    "ebook": {".epub", ".mobi", ".azw", ".azw3", ".pdf", ".djvu", ".fb2"},
    "audiobook": {".m4b", ".aa", ".aax"},
    "music": {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aiff"},
    "comic": {".cbz", ".cbr", ".cb7"},
    "photo": {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".dng", ".cr2", ".nef", ".arw"},
    "sidecar": {".nfo", ".opf", ".srt", ".ass", ".vtt", ".xmp", ".xml"},
}
VALID_MEDIA = frozenset({"films", "television", "anime", "ebooks", "audiobooks", "music", "comics", "photographs", "home-videos", "other"})
VALID_APPS = frozenset({"plex", "jellyfin", "emby", "calibre", "audiobookshelf", "kavita", "komga", "navidrome", "folders"})
SCAN_PROFILES = frozenset({"quiet", "balanced", "fast"})

def classify(name: str) -> str:
    suffix = Path(name).suffix.lower()
    for kind, extensions in KINDS.items():
        if suffix in extensions:
            return kind
    return "other"

def utc_now() -> float:
    return time.time()

class Catalogue:
    def __init__(self, directory: Path):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / "catalogue.sqlite3"
        self.write_lock = threading.RLock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS libraries (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                    root TEXT UNIQUE NOT NULL, media_types TEXT NOT NULL,
                    applications TEXT NOT NULL,
                    scan_profile TEXT NOT NULL DEFAULT 'balanced',
                    added_at REAL NOT NULL,
                    last_scan_at REAL
                );
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY, library_id INTEGER NOT NULL
                      REFERENCES libraries(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL, kind TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    observed_at REAL NOT NULL,
                    UNIQUE(library_id, relative_path)
                );
                CREATE INDEX IF NOT EXISTS files_library ON files(library_id);
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, library_id INTEGER NOT NULL,
                    state TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0,
                    changed INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
            """)
            if "scan_profile" not in {
                row["name"] for row in db.execute("PRAGMA table_info(libraries)")
            }:
                db.execute("ALTER TABLE libraries ADD COLUMN scan_profile TEXT NOT NULL DEFAULT 'balanced'")
            # A process can disappear mid-scan. The next start can resume safely
            # by rescanning; untouched files remain in the catalogue.
            db.execute("UPDATE jobs SET state='paused', message='Interrupted on restart' WHERE state='running'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _dict(row):
        if row is None:
            return None
        return dict(row)

    def libraries(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM libraries ORDER BY id").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["media_types"] = json.loads(item["media_types"])
            item["applications"] = json.loads(item["applications"])
            result.append(item)
        return result

    def library(self, library_id: int):
        return next((lib for lib in self.libraries() if lib["id"] == library_id), None)

    def add_library(self, name: str, root: Path, media_types: list[str],
                    applications: list[str], scan_profile: str = "balanced"):
        root = root.expanduser()
        if not root.is_absolute() or root.is_symlink() or not root.is_dir():
            raise ValueError("Choose an existing, absolute directory (not a symbolic link).")
        root = root.resolve(strict=True)
        if self.directory == root or self.directory.is_relative_to(root) or root.is_relative_to(self.directory):
            raise ValueError("The catalogue directory cannot be inside the media root, or vice versa.")
        if not name.strip() or len(name) > 100:
            raise ValueError("Enter a library name of 1–100 characters.")
        if not media_types or not set(media_types).issubset(VALID_MEDIA):
            raise ValueError("Select at least one recognised media type.")
        if not set(applications).issubset(VALID_APPS):
            raise ValueError("Unknown media application.")
        if scan_profile not in SCAN_PROFILES:
            raise ValueError("Unknown resource profile.")
        for item in self.libraries():
            existing = Path(item["root"])
            if root.is_relative_to(existing) or existing.is_relative_to(root):
                raise ValueError("Overlapping library folders cannot be indexed separately.")
        try:
            with self.write_lock, self.connect() as db:
                cursor = db.execute(
                    "INSERT INTO libraries(name,root,media_types,applications,scan_profile,added_at) VALUES(?,?,?,?,?,?)",
                    (name.strip(), str(root), json.dumps(sorted(set(media_types))),
                     json.dumps(sorted(set(applications))), scan_profile, utc_now())
                )
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("This folder is already registered.") from exc

    def jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 40")]

    def job(self, job_id: int):
        with self.connect() as db:
            return self._dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def new_job(self, library_id: int):
        with self.write_lock, self.connect() as db:
            cursor = db.execute(
                "INSERT INTO jobs(library_id,state,created_at,updated_at) VALUES(?,'running',?,?)",
                (library_id, utc_now(), utc_now())
            )
            return cursor.lastrowid

    def update_job(self, job_id: int, state: str | None = None,
                   seen: int | None = None, changed: int | None = None,
                   errors: int | None = None, message: str | None = None):
        fields, args = ["updated_at=?"], [utc_now()]
        for key, val in (("state", state), ("seen", seen), ("changed", changed),
                         ("errors", errors), ("message", message)):
            if val is not None:
                fields.append(f"{key}=?")
                args.append(val)
        with self.write_lock, self.connect() as db:
            db.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?",
                       (*args, job_id))

    def upsert_batch(self, library_id: int, files: list[tuple[str, str, int, int, float]]):
        if not files:
            return
        with self.write_lock, self.connect() as db:
            db.executemany(
                """INSERT INTO files(library_id,relative_path,kind,size,mtime_ns,observed_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(library_id,relative_path)
                   DO UPDATE SET kind=excluded.kind,size=excluded.size,
                      mtime_ns=excluded.mtime_ns,observed_at=excluded.observed_at""",
                [(library_id, *f) for f in files]
            )

    def finalise_scan(self, library_id: int, started: float):
        # Only prune after a complete scan with no errors. Otherwise an offline
        # share would look rather convincingly like an empty library.
        with self.write_lock, self.connect() as db:
            db.execute("DELETE FROM files WHERE library_id=? AND observed_at<?",
                       (library_id, started))
            db.execute("UPDATE libraries SET last_scan_at=? WHERE id=?",
                       (utc_now(), library_id))

    def files(self, library_id: int, limit: int = 100, search: str = ""):
        with self.connect() as db:
            if search:
                escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = db.execute(
                    """SELECT relative_path,kind,size,mtime_ns FROM files
                       WHERE library_id=? AND relative_path LIKE ? ESCAPE '\\'
                       ORDER BY relative_path LIMIT ?""",
                    (library_id, f"%{escaped}%", limit)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT relative_path,kind,size,mtime_ns FROM files WHERE library_id=? ORDER BY relative_path LIMIT ?",
                    (library_id, limit)
                ).fetchall()
        return [dict(row) for row in rows]

    def status(self):
        with self.connect() as db:
            libraries = db.execute("SELECT COUNT(*) FROM libraries").fetchone()[0]
            files = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            kinds = {r["kind"]: r["n"] for r in db.execute(
                "SELECT kind, COUNT(*) AS n FROM files GROUP BY kind ORDER BY kind")}
        return {"libraries": libraries, "files": files, "by_kind": kinds,
                "mode": "read-only", "version": "0.1.0-alpha"}
