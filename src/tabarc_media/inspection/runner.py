"""Run an inventory scan and store the results in the catalogue.

Behaviour worth knowing:

- Unchanged files (same size and mtime) are not probed again. That is
  what makes a re-run after an interruption cheap on a big NAS.
- Transient probe failures (timeouts, OS errors) are retried next scan.
  A file ffprobe rejects outright is not, until the file changes.
- Per-file issues (bad probe, undecodable name) are recorded in the scan
  where they first appear, not repeated on every scan after.
- Files not seen in this scan are marked not present, never deleted, and
  only for roots that scanned without issues. An unmounted share must not
  turn the whole catalogue into "missing".
- Progress is committed every COMMIT_EVERY files.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from tabarc_media.config.loader import Config
from tabarc_media.inspection.inventory import (
    INCOMPLETE_ISSUES,
    FileRecord,
    ScanIssue,
    probe_video,
    walk_root,
)

COMMIT_EVERY = 500
PROGRESS_EVERY = 1000


@dataclass
class ScanSummary:
    job_id: int
    status: str = "running"
    files_seen: int = 0
    files_new: int = 0
    files_changed: int = 0
    files_unchanged: int = 0
    files_missing: int = 0
    issues: int = 0
    probes_run: int = 0
    probes_failed: int = 0
    roots_not_reconciled: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_issue(conn: sqlite3.Connection, job_id: int, issue: ScanIssue) -> None:
    conn.execute(
        "INSERT INTO scan_issues (scan_id, root, rel_path, kind, detail) VALUES (?, ?, ?, ?, ?)",
        (job_id, issue.root, issue.rel_path, issue.kind, issue.detail),
    )


def _note(conn: sqlite3.Connection, s: ScanSummary, issue: ScanIssue) -> None:
    _record_issue(conn, s.job_id, issue)
    s.issues += 1


def _needs_probe(probe_ok: int | None, probe_json: str | None) -> bool:
    if probe_ok is None:
        return True          # never probed, or file changed
    if probe_ok == 1:
        return False
    try:
        return bool(json.loads(probe_json or "{}").get("transient"))
    except json.JSONDecodeError:
        return True


def _store_file(conn, rec: FileRecord, probe: bool, timeout: int, s: ScanSummary) -> None:
    row = conn.execute(
        "SELECT size_bytes, mtime_ns, probe_json, probe_ok, probed_at "
        "FROM media_files WHERE root = ? AND rel_path_raw = ?",
        (rec.root, rec.rel_path_raw),
    ).fetchone()
    now = _now()

    changed = row is None or (row["size_bytes"], row["mtime_ns"]) != (rec.size_bytes, rec.mtime_ns)
    if row is None:
        s.files_new += 1
    elif changed:
        s.files_changed += 1
    else:
        s.files_unchanged += 1

    # Old probe data describes old bytes, so drop it if the file changed.
    if changed:
        probe_json = probe_ok = probed_at = None
    else:
        probe_json, probe_ok, probed_at = row["probe_json"], row["probe_ok"], row["probed_at"]

    if changed and not rec.name_decodable:
        _note(conn, s, ScanIssue(rec.root, rec.rel_path, "undecodable_name",
                                 "Name is not valid UTF-8. Recorded, but later stages "
                                 "will not rename it."))

    if probe and rec.media_kind == "video" and _needs_probe(probe_ok, probe_json):
        result = probe_video(rec.abs_path, timeout)
        s.probes_run += 1
        probe_ok = 0 if "error" in result else 1
        if not probe_ok:
            s.probes_failed += 1
            _note(conn, s, ScanIssue(rec.root, rec.rel_path, "probe_failed",
                                     str(result["error"])))
        probe_json, probed_at = json.dumps(result), now

    conn.execute(
        """
        INSERT INTO media_files
            (root, rel_path, rel_path_raw, name_decodable, size_bytes, mtime_ns,
             extension, media_kind, probe_json, probe_ok, probed_at, present,
             first_seen_at, last_seen_at, last_seen_scan_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT (root, rel_path_raw) DO UPDATE SET
            rel_path          = excluded.rel_path,
            name_decodable    = excluded.name_decodable,
            size_bytes        = excluded.size_bytes,
            mtime_ns          = excluded.mtime_ns,
            extension         = excluded.extension,
            media_kind        = excluded.media_kind,
            probe_json        = excluded.probe_json,
            probe_ok          = excluded.probe_ok,
            probed_at         = excluded.probed_at,
            present           = 1,
            last_seen_at      = excluded.last_seen_at,
            last_seen_scan_id = excluded.last_seen_scan_id
        """,
        (rec.root, rec.rel_path, rec.rel_path_raw, int(rec.name_decodable),
         rec.size_bytes, rec.mtime_ns, rec.extension, rec.media_kind,
         probe_json, probe_ok, probed_at, now, now, s.job_id),
    )


def _scan_root(conn, root, cfg: Config, probe: bool, s: ScanSummary,
               progress: Callable[[ScanSummary], None] | None) -> None:
    complete = True
    for item in walk_root(root, cfg.inventory):
        if isinstance(item, ScanIssue):
            _note(conn, s, item)
            if item.kind in INCOMPLETE_ISSUES:
                complete = False
            continue
        _store_file(conn, item, probe, cfg.inventory.probe_timeout_seconds, s)
        s.files_seen += 1
        if s.files_seen % COMMIT_EVERY == 0:
            conn.commit()
        if progress and s.files_seen % PROGRESS_EVERY == 0:
            progress(s)

    if complete:
        cur = conn.execute(
            "UPDATE media_files SET present = 0 "
            "WHERE root = ? AND present = 1 AND last_seen_scan_id != ?",
            (str(root), s.job_id),
        )
        s.files_missing += cur.rowcount
    else:
        s.roots_not_reconciled.append(str(root))
    conn.commit()


def _finish(conn: sqlite3.Connection, s: ScanSummary) -> None:
    conn.execute(
        """
        UPDATE scan_jobs SET
            finished_at = ?, status = ?, files_seen = ?, files_new = ?,
            files_changed = ?, files_unchanged = ?, files_missing = ?,
            issues = ?, probes_run = ?, probes_failed = ?
        WHERE id = ?
        """,
        (_now(), s.status, s.files_seen, s.files_new, s.files_changed,
         s.files_unchanged, s.files_missing, s.issues, s.probes_run,
         s.probes_failed, s.job_id),
    )
    conn.commit()


def run_inventory(conn: sqlite3.Connection, cfg: Config, *, probe: bool,
                  progress: Callable[[ScanSummary], None] | None = None) -> ScanSummary:
    """Scan every configured root. Returns a summary; never deletes rows.

    Ctrl-C is caught and recorded as "interrupted". Any other exception is
    recorded as "failed" and re-raised.
    """
    cur = conn.execute(
        "INSERT INTO scan_jobs (started_at, status, roots_json) VALUES (?, 'running', ?)",
        (_now(), json.dumps([str(r) for r in cfg.roots])),
    )
    conn.commit()
    s = ScanSummary(job_id=cur.lastrowid)
    try:
        for root in cfg.roots:
            _scan_root(conn, root, cfg, probe, s, progress)
        s.status = "complete" if s.issues == 0 else "complete_with_issues"
    except KeyboardInterrupt:
        s.status = "interrupted"
    except BaseException:
        s.status = "failed"
        raise
    finally:
        try:
            _finish(conn, s)
        except sqlite3.Error:
            # Don't let a broken connection hide the original error.
            if s.status != "failed":
                raise
    return s
