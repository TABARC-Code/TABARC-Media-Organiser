"""TABARC Media Organiser. Stage 1: read-only inventory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tabarc_media import __version__
from tabarc_media.catalogue.db import CatalogueError, connect
from tabarc_media.config.loader import ConfigError, load_config
from tabarc_media.inspection.inventory import ffprobe_available
from tabarc_media.inspection.runner import ScanSummary, run_inventory

DEFAULT_CONFIG = Path("~/.config/tabarc-media/config.toml")

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_ISSUES = 3
EXIT_INTERRUPTED = 130
EXIT_CODES = {
    "complete": EXIT_OK,
    "complete_with_issues": EXIT_ISSUES,
    "interrupted": EXIT_INTERRUPTED,
}


def _progress(s: ScanSummary) -> None:
    print(f"  ... {s.files_seen} files, {s.probes_run} probed, {s.issues} issues",
          file=sys.stderr, flush=True)


def _print_summary(s: ScanSummary) -> None:
    print(f"Inventory {s.status} (scan {s.job_id})")
    print(f"  files seen        {s.files_seen}")
    print(f"  new / changed     {s.files_new} / {s.files_changed}")
    print(f"  unchanged         {s.files_unchanged}")
    print(f"  marked missing    {s.files_missing}")
    print(f"  probes run/failed {s.probes_run} / {s.probes_failed}")
    print(f"  issues            {s.issues}")
    if s.issues:
        print(f"  Run 'tabarc-media issues --scan {s.job_id}' for details.")
    for root in s.roots_not_reconciled:
        print(f"  Not reconciled: {root} (missing-file check skipped because of issues)")


def cmd_inventory(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if not cfg.roots:
        print("No library roots configured. Add paths under [libraries] roots.", file=sys.stderr)
        return EXIT_CONFIG

    probe = cfg.inventory.probe_video and not args.no_probe
    if probe and not ffprobe_available():
        print("Warning: ffprobe not found on PATH. Video technical data won't be recorded.",
              file=sys.stderr)
        probe = False

    conn = connect(cfg.database_path)
    try:
        summary = run_inventory(conn, cfg, probe=probe,
                                progress=None if args.quiet else _progress)
    finally:
        conn.close()
    _print_summary(summary)
    return EXIT_CODES[summary.status]


def cmd_issues(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    conn = connect(cfg.database_path)
    try:
        scan_id = args.scan
        if scan_id is None:
            row = conn.execute("SELECT MAX(id) AS id FROM scan_jobs").fetchone()
            scan_id = row["id"]
        if scan_id is None:
            print("No scans recorded yet.")
            return EXIT_OK
        rows = conn.execute(
            "SELECT root, rel_path, kind, detail FROM scan_issues WHERE scan_id = ? ORDER BY id",
            (scan_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print(f"No issues recorded for scan {scan_id}.")
        return EXIT_OK
    print(f"{len(rows)} issue(s) for scan {scan_id}:")
    for r in rows:
        where = f"{r['root']}/{r['rel_path']}" if r["rel_path"] else r["root"]
        print(f"  [{r['kind']}] {where}\n      {r['detail']}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tabarc-media", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG.expanduser()),
        help="Path to a TOML config file (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="Read-only scan of configured library roots")
    inv.add_argument("--no-probe", action="store_true",
                     help="Skip ffprobe for this run (fast first pass)")
    inv.add_argument("--quiet", action="store_true", help="No progress output")
    inv.set_defaults(func=cmd_inventory)

    iss = sub.add_parser("issues", help="List issues from a scan (default: latest)")
    iss.add_argument("--scan", type=int, help="Scan id")
    iss.set_defaults(func=cmd_issues)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, CatalogueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
