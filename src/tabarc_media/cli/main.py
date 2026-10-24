"""TABARC Media Organiser. Stage 1: read-only inventory."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from tabarc_media import __version__
from tabarc_media.catalogue.db import CatalogueError, ScanLock, connect
from tabarc_media.catalogue.stats import collect, human_size
from tabarc_media.config.loader import ConfigError, KNOWN_PROVIDERS, load_config, write_initial_config
from tabarc_media.identity.credits import CREDITS
from tabarc_media.identity.queue import resolve
from tabarc_media.identity.runner import run_identify
from tabarc_media.inspection.inventory import ffprobe_available
from tabarc_media.inspection.runner import ScanSummary, run_inventory

DEFAULT_CONFIG = Path(os.environ.get("TABARC_CONFIG", "~/.config/tabarc-media/config.toml"))

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
    if s.abandoned_before:
        print(f"  Earlier scan(s) that never finished were marked abandoned: {s.abandoned_before}")
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

    with ScanLock(cfg.database_path):
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


def cmd_init(args: argparse.Namespace) -> int:
    path = Path(args.config).expanduser()
    cfg = write_initial_config(path, args.roots)
    print(f"Wrote {path}")
    print(f"  catalogue: {cfg.database_path}")
    if cfg.roots:
        for root in cfg.roots:
            print(f"  root:      {root}")
        print("Next: tabarc-media inventory --no-probe   (quick first pass)")
    else:
        print("No library roots yet. Edit the file and add them under [libraries] roots,")
        print("or rerun with: tabarc-media init --roots /mnt/nas/Movies /mnt/nas/TV")
        print("(delete the file first; init won't overwrite).")
    return EXIT_OK


def cmd_stats(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if not cfg.database_path.is_file():
        print(f"No catalogue at {cfg.database_path} yet. Run 'tabarc-media inventory' first.")
        return EXIT_CONFIG
    conn = connect(cfg.database_path)
    try:
        st = collect(conn, cfg.roots)
    finally:
        conn.close()

    if st.last_scan is None:
        print("Catalogue exists but no scan has been recorded.")
        return EXIT_OK
    ls = st.last_scan
    print(f"Last scan {ls['id']}: {ls['status']}, started {ls['started_at']}")
    total_files = total_bytes = 0
    for r in st.roots:
        note = "" if r.configured else "  (no longer in config)"
        print(f"\n{r.root}{note}")
        print(f"  present  {r.present} files, {human_size(r.present_bytes)}")
        if r.missing:
            print(f"  missing  {r.missing} (marked not present, still in the catalogue)")
        for kind, n in r.by_kind.items():
            print(f"    {kind:<8} {n}")
        total_files += r.present
        total_bytes += r.present_bytes
    print(f"\nTotal present: {total_files} files, {human_size(total_bytes)}")
    print("Video probes: "
          f"{st.videos_probed_ok} ok, {st.videos_probe_failed} failed, "
          f"{st.videos_not_probed} not probed")
    if st.undecodable_names:
        print(f"Undecodable filenames: {st.undecodable_names}")
    return EXIT_OK


def cmd_identify(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    if cfg.providers.offline:
        print("Offline mode is on in the config, so no lookups were made.")
        return EXIT_OK
    if not cfg.providers.contact:
        raise ConfigError(
            "Set contact under [providers] in the config before running lookups. "
            "An email address is ideal. Free metadata services ask who is calling."
        )
    if not cfg.providers.enabled:
        raise ConfigError("No providers are enabled under [providers] enabled.")

    with ScanLock(cfg.database_path):
        conn = connect(cfg.database_path)
        try:
            summary = run_identify(conn, cfg, limit=args.limit)
        finally:
            conn.close()

    print(f"Identify: {summary.considered} looked up, {summary.fresh_skipped} reused from earlier.")
    for status in ("matched", "pending", "none", "skipped", "no_provider"):
        if summary.counts.get(status):
            print(f"  {status:<12}{summary.counts[status]}")
    for name, calls in summary.provider_calls.items():
        print(f"  {name} calls: {calls}")
    if summary.counts.get("pending"):
        print("Run 'tabarc-media review' to look at the ones that need a person.")
    if summary.providers_failed:
        print("Some lookups failed. Nothing was recorded for files where every source failed.")
        return EXIT_ISSUES
    return EXIT_OK


def _candidates(row) -> list[dict]:
    return json.loads(row["candidates"])


def cmd_review_list(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    conn = connect(cfg.database_path)
    try:
        rows = conn.execute(
            "SELECT * FROM identity_matches WHERE status = ? ORDER BY root, rel_path LIMIT ?",
            (args.status, args.limit),
        ).fetchall()
        if not rows:
            print(f"Nothing with status '{args.status}'.")
            return EXIT_OK
        for r in rows:
            print(f"#{r['id']}  {r['status']}  {r['rel_path']}")
            print(f"    why: {r['reason']}")
            if r["providers_failed"]:
                print(f"    sources that failed: {r['providers_failed']}")
            for n, c in enumerate(_candidates(r)[:3], 1):
                year = f" ({c['year']})" if c["year"] else ""
                print(f"    {n}. {c['score']:.2f}  {c['title']}{year}  {c['kind']}  "
                      f"{c['provider']} {c['provider_id']}")
        print(f"{len(rows)} shown. Accept with: review accept ID --candidate N")
    finally:
        conn.close()
    return EXIT_OK


def cmd_review_accept(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    conn = connect(cfg.database_path)
    try:
        row = conn.execute("SELECT * FROM identity_matches WHERE id = ?", (args.id,)).fetchone()
        if row is None:
            print(f"No entry #{args.id}.", file=sys.stderr)
            return EXIT_CONFIG
        cands = _candidates(row)
        if not 1 <= args.candidate <= len(cands):
            print(f"Entry #{args.id} has {len(cands)} candidate(s). Pick 1 to {len(cands)}.",
                  file=sys.stderr)
            return EXIT_CONFIG
        chosen = cands[args.candidate - 1]
        resolve(conn, args.id, "accept", chosen["provider"], chosen["provider_id"])
        print(f"Accepted #{args.id}: {chosen['title']} ({chosen['provider']} "
              f"{chosen['provider_id']}). No files were changed.")
    finally:
        conn.close()
    return EXIT_OK


def cmd_review_reject(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.config))
    conn = connect(cfg.database_path)
    try:
        row = conn.execute("SELECT id FROM identity_matches WHERE id = ?", (args.id,)).fetchone()
        if row is None:
            print(f"No entry #{args.id}.", file=sys.stderr)
            return EXIT_CONFIG
        resolve(conn, args.id, "reject")
        print(f"Rejected #{args.id}. It won't be looked up again unless you clear it.")
    finally:
        conn.close()
    return EXIT_OK


def cmd_about(args: argparse.Namespace) -> int:
    enabled = list(KNOWN_PROVIDERS)
    try:
        enabled = list(load_config(Path(args.config)).providers.enabled)
    except ConfigError:
        pass  # no usable config yet, so show every source we could use
    print(f"TABARC Media Organiser {__version__}")
    print("Author: TABARC-Code. MIT licence.")
    print()
    print("Data sources:")
    for name in KNOWN_PROVIDERS:
        marker = "enabled " if name in enabled else "disabled"
        print(f"  [{marker}] {CREDITS[name]}")
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

    ini = sub.add_parser("init", help="Write a starter config (won't overwrite an existing one)")
    ini.add_argument("--roots", nargs="*", default=[], metavar="PATH",
                     help="Absolute library root paths to put in the config")
    ini.set_defaults(func=cmd_init)

    sta = sub.add_parser("stats", help="Summarise what the catalogue holds (read-only)")
    sta.set_defaults(func=cmd_stats)

    iss = sub.add_parser("issues", help="List issues from a scan (default: latest)")
    iss.add_argument("--scan", type=int, help="Scan id")
    iss.set_defaults(func=cmd_issues)

    ide = sub.add_parser("identify", help="Look files up in the enabled sources (read-only)")
    ide.add_argument("--limit", type=int, help="Look up at most this many files this run")
    ide.set_defaults(func=cmd_identify)

    rev = sub.add_parser("review", help="Look at matches that need a person")
    rev_sub = rev.add_subparsers(dest="review_command", required=True)
    rl = rev_sub.add_parser("list", help="Show queued matches")
    rl.add_argument("--status", default="pending",
                    choices=["pending", "none", "matched", "accepted", "rejected"])
    rl.add_argument("--limit", type=int, default=20)
    rl.set_defaults(func=cmd_review_list)
    ra = rev_sub.add_parser("accept", help="Accept one of the listed candidates")
    ra.add_argument("id", type=int)
    ra.add_argument("--candidate", type=int, required=True, help="Number from the list")
    ra.set_defaults(func=cmd_review_accept)
    rr = rev_sub.add_parser("reject", help="Reject a match")
    rr.add_argument("id", type=int)
    rr.set_defaults(func=cmd_review_reject)

    abt = sub.add_parser("about", help="Version, licence and data source credits")
    abt.set_defaults(func=cmd_about)
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
