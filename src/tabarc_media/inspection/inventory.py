"""Read-only walk of one media root.

Nothing here writes anywhere. The walk yields FileRecord objects for files
it can read and ScanIssue objects for anything it couldn't, so a folder
the scanner can't open is reported rather than silently skipped. That
matters: a silent gap looks exactly like a deleted folder.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from tabarc_media.config.loader import InventoryConfig

VIDEO_EXTENSIONS = frozenset({
    ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".webm", ".wmv", ".mpg", ".mpeg",
})
BOOK_EXTENSIONS = frozenset({".epub", ".pdf", ".mobi", ".azw3"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".m4a"})
COMIC_EXTENSIONS = frozenset({".cbz", ".cbr"})

# Issue kinds that mean part of a root may not have been seen. If any of
# these occur, the runner will not mark unseen files as missing.
INCOMPLETE_ISSUES = frozenset({
    "root_missing", "root_empty", "root_unreadable", "dir_unreadable", "file_unreadable",
})


@dataclass(frozen=True)
class FileRecord:
    root: str
    rel_path: str          # display text; lossless when the name is valid UTF-8
    rel_path_raw: bytes    # exact on-disk bytes, used as the key
    name_decodable: bool
    size_bytes: int
    mtime_ns: int
    extension: str
    media_kind: str

    @property
    def abs_path(self) -> str:
        return os.path.join(self.root, os.fsdecode(self.rel_path_raw))


@dataclass(frozen=True)
class ScanIssue:
    root: str
    rel_path: str
    kind: str
    detail: str


def media_kind_for(extension: str) -> str:
    """Map a file extension to a coarse media kind."""
    ext = extension.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in BOOK_EXTENSIONS:
        return "book"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in COMIC_EXTENSIONS:
        return "comic"
    return "other"


def _classify(ext: str, cfg: InventoryConfig) -> str | None:
    if ext in cfg.media_extensions:
        return media_kind_for(ext)
    if ext in cfg.sidecar_extensions:
        return "sidecar"
    return None


def _describe(exc: OSError) -> str:
    return f"{type(exc).__name__}: {exc.strerror or exc}"


def _rel_text(rel: Path) -> tuple[bytes, str, bool]:
    raw = os.fsencode(rel)
    try:
        return raw, raw.decode("utf-8"), True
    except UnicodeDecodeError:
        return raw, raw.decode("utf-8", "backslashreplace"), False


def walk_root(root: Path, cfg: InventoryConfig) -> Iterator[FileRecord | ScanIssue]:
    """Yield records and issues for one root, in a stable order.

    - Symlinks (files and folders) are skipped, so the walk can't escape
      the root or loop.
    - Excluded folder names are skipped at any depth, case-insensitively.
    - macOS AppleDouble files ("._name.mkv") are skipped. They turn up on
      SMB shares and would otherwise pass as media.
    """
    root = Path(root)
    if not root.is_absolute():
        raise ValueError(f"Library root must be absolute: {root}")
    root_s = str(root)

    if not root.is_dir():
        yield ScanIssue(root_s, "", "root_missing",
                        "Root is not a directory. Is the share mounted?")
        return
    try:
        with os.scandir(root) as it:
            empty = next(it, None) is None
    except OSError as exc:
        yield ScanIssue(root_s, "", "root_unreadable", _describe(exc))
        return
    if empty:
        # An unmounted share usually leaves an empty mount point behind.
        yield ScanIssue(root_s, "", "root_empty",
                        "Root is empty. If the share isn't mounted, nothing was scanned.")
        return

    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            _, text, _ = _rel_text(current.relative_to(root))
            yield ScanIssue(root_s, text, "dir_unreadable", _describe(exc))
            continue

        subdirs: list[Path] = []
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.lower() not in cfg.exclude_dirs:
                        subdirs.append(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.name.startswith("._"):
                    continue
                ext = os.path.splitext(entry.name)[1].lower()
                kind = _classify(ext, cfg)
                if kind is None:
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                _, text, _ = _rel_text(entry_path.relative_to(root))
                yield ScanIssue(root_s, text, "file_unreadable", _describe(exc))
                continue

            # Undecodable names are flagged by the runner, once, when the
            # file is first seen. Flagging here would repeat it every scan.
            raw, text, decodable = _rel_text(entry_path.relative_to(root))
            yield FileRecord(
                root=root_s,
                rel_path=text,
                rel_path_raw=raw,
                name_decodable=decodable,
                size_bytes=st.st_size,
                mtime_ns=st.st_mtime_ns,
                extension=ext,
                media_kind=kind,
            )
        # Reverse so the stack pops folders in alphabetical order.
        stack.extend(reversed(subdirs))


# ---------------------------------------------------------------- ffprobe

def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_video(path: str, timeout: int) -> dict:
    """Run ffprobe read-only on one file.

    Always returns a dict. Failures come back as {"error": ..., "transient": bool}.
    Transient failures (timeout, OS error, typical of a flaky share) are
    worth retrying next scan. A non-zero ffprobe exit usually means the
    file itself is bad, and retrying it every scan just burns time.
    """
    if not os.path.isabs(path):
        # An absolute path can't be mistaken for an ffprobe option.
        raise ValueError(f"probe_video needs an absolute path: {path}")
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",   # tags with odd bytes must not crash the scan
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s", "transient": True}
    except OSError as exc:
        return {"error": _describe(exc), "transient": True}
    if result.returncode != 0:
        detail = result.stderr.strip()[:500] or f"exit code {result.returncode}"
        return {"error": detail, "transient": False}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "unparseable ffprobe output", "transient": False}
