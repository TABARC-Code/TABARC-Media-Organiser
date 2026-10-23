"""SQLite catalogue.

Standard library only for now. Migrations move to Alembic when the schema
grows past Stage 1.

The catalogue is an index. It can always be rebuilt by re-scanning, so
nothing here is the only copy of anything. Even so, rows are never
deleted by the inventory: files that disappear are marked not present.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

# Filesystem types where SQLite locking is unreliable. SQLite's own docs
# warn against network filesystems; this list is the common Linux names.
NETWORK_FS_TYPES = frozenset({
    "cifs", "smb3", "smbfs", "nfs", "nfs4", "afpfs", "9p",
    "fuse.sshfs", "fuse.rclone", "davfs", "fuse.davfs2",
})

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_jobs (
    id               INTEGER PRIMARY KEY,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    status           TEXT NOT NULL,
    roots_json       TEXT NOT NULL,
    files_seen       INTEGER NOT NULL DEFAULT 0,
    files_new        INTEGER NOT NULL DEFAULT 0,
    files_changed    INTEGER NOT NULL DEFAULT 0,
    files_unchanged  INTEGER NOT NULL DEFAULT 0,
    files_missing    INTEGER NOT NULL DEFAULT 0,
    issues           INTEGER NOT NULL DEFAULT 0,
    probes_run       INTEGER NOT NULL DEFAULT 0,
    probes_failed    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS media_files (
    id                 INTEGER PRIMARY KEY,
    root               TEXT NOT NULL,
    rel_path           TEXT NOT NULL,   -- display text
    rel_path_raw       BLOB NOT NULL,   -- exact on-disk bytes; the real key
    name_decodable     INTEGER NOT NULL,
    size_bytes         INTEGER NOT NULL,
    mtime_ns           INTEGER NOT NULL,
    extension          TEXT NOT NULL,
    media_kind         TEXT NOT NULL,
    probe_json         TEXT,
    probe_ok           INTEGER,
    probed_at          TEXT,
    present            INTEGER NOT NULL DEFAULT 1,
    first_seen_at      TEXT NOT NULL,
    last_seen_at       TEXT NOT NULL,
    last_seen_scan_id  INTEGER NOT NULL REFERENCES scan_jobs (id),
    UNIQUE (root, rel_path_raw)
);
CREATE INDEX IF NOT EXISTS idx_media_files_root_seen
    ON media_files (root, last_seen_scan_id);
CREATE TABLE IF NOT EXISTS scan_issues (
    id        INTEGER PRIMARY KEY,
    scan_id   INTEGER NOT NULL REFERENCES scan_jobs (id),
    root      TEXT NOT NULL,
    rel_path  TEXT NOT NULL,
    kind      TEXT NOT NULL,
    detail    TEXT NOT NULL
);
"""


class CatalogueError(RuntimeError):
    """Raised when the catalogue cannot be opened safely."""


class ScanLock:
    """Exclusive lock so only one scan writes to a catalogue at a time.

    Two scans at once would each mark the other's files missing. Uses
    flock on a file next to the database, so the lock dies with the
    process: a crash or kill -9 can't leave it stuck. On systems without
    fcntl (Windows) this is a no-op, which the README says.
    """

    def __init__(self, db_path: Path):
        db_path = Path(db_path).expanduser()
        self.path = db_path.with_name(db_path.name + ".lock")
        self._fh = None

    def __enter__(self) -> "ScanLock":
        try:
            import fcntl
        except ImportError:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            raise CatalogueError(
                "Another scan is already running against this catalogue. "
                "Wait for it to finish, or stop it."
            ) from None
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        if self._fh is not None:
            import fcntl
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


def _unescape_mount(field: str) -> str:
    # /proc/mounts escapes spaces, tabs, newlines and backslashes as octal.
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def filesystem_type(path: Path, mounts_file: Path = Path("/proc/self/mounts")) -> str | None:
    """Return the filesystem type holding *path*, or None if unknown.

    Linux only: reads the mount table. On other systems it returns None
    and no network check happens, which the README says plainly.
    """
    if not mounts_file.is_file():
        return None
    target = Path(os.path.abspath(path))
    while not target.exists() and target != target.parent:
        target = target.parent
    target_str = str(target.resolve())

    best_len, fstype = -1, None
    for line in mounts_file.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = _unescape_mount(parts[1])
        prefix = mount_point.rstrip("/") + "/"
        if target_str == mount_point or target_str.startswith(prefix):
            if len(mount_point) > best_len:
                best_len, fstype = len(mount_point), parts[2]
    return fstype


def connect(path: Path) -> sqlite3.Connection:
    """Open the catalogue, creating it on first use.

    Refuses to open a database on a network filesystem (Linux only, see
    filesystem_type) and refuses a database written by a different
    schema version rather than guessing.
    """
    path = Path(path).expanduser()
    fstype = filesystem_type(path)
    if fstype in NETWORK_FS_TYPES:
        raise CatalogueError(
            f"Catalogue path {path} is on a network filesystem ({fstype}). "
            "SQLite is not safe there. Put the database on local disk."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)

    row = conn.execute("SELECT value FROM schema_info WHERE key = 'version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_info (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    elif row["value"] != str(SCHEMA_VERSION):
        conn.close()
        raise CatalogueError(
            f"Catalogue schema version is {row['value']}, this build expects "
            f"{SCHEMA_VERSION}. Refusing to touch it."
        )
    return conn
