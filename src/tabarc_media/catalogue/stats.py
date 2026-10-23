"""Read-only summary of what the catalogue holds.

Everything here is a SELECT. Useful after a first NAS scan, mostly to
check the catalogue agrees with what you think is on the box.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RootStats:
    root: str
    configured: bool
    present: int = 0
    missing: int = 0
    present_bytes: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


@dataclass
class CatalogueStats:
    last_scan: sqlite3.Row | None
    roots: list[RootStats]
    videos_probed_ok: int
    videos_probe_failed: int
    videos_not_probed: int
    undecodable_names: int


def human_size(n: int) -> str:
    """Binary units, because that's what df and most NAS dashboards show."""
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def collect(conn: sqlite3.Connection, configured_roots: tuple[Path, ...]) -> CatalogueStats:
    configured = [str(r) for r in configured_roots]
    seen = [r[0] for r in conn.execute("SELECT DISTINCT root FROM media_files ORDER BY root")]

    roots: list[RootStats] = []
    for root in configured + [r for r in seen if r not in configured]:
        rs = RootStats(root=root, configured=root in configured)
        row = conn.execute(
            "SELECT COALESCE(SUM(present), 0), COALESCE(SUM(1 - present), 0), "
            "COALESCE(SUM(CASE WHEN present = 1 THEN size_bytes END), 0) "
            "FROM media_files WHERE root = ?",
            (root,),
        ).fetchone()
        rs.present, rs.missing, rs.present_bytes = row[0], row[1], row[2]
        rs.by_kind = {
            kind: n for kind, n in conn.execute(
                "SELECT media_kind, COUNT(*) FROM media_files "
                "WHERE root = ? AND present = 1 GROUP BY media_kind ORDER BY media_kind",
                (root,),
            )
        }
        roots.append(rs)

    probe = conn.execute(
        "SELECT "
        "  COALESCE(SUM(probe_ok = 1), 0), "
        "  COALESCE(SUM(probe_ok = 0), 0), "
        "  COALESCE(SUM(probe_ok IS NULL), 0) "
        "FROM media_files WHERE media_kind = 'video' AND present = 1"
    ).fetchone()

    return CatalogueStats(
        last_scan=conn.execute("SELECT * FROM scan_jobs ORDER BY id DESC LIMIT 1").fetchone(),
        roots=roots,
        videos_probed_ok=probe[0],
        videos_probe_failed=probe[1],
        videos_not_probed=probe[2],
        undecodable_names=conn.execute(
            "SELECT COUNT(*) FROM media_files WHERE name_decodable = 0 AND present = 1"
        ).fetchone()[0],
    )
