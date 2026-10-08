"""Incremental, deliberately unhurried scans of approved library roots."""

import os
import threading
import time
from pathlib import Path

from .catalogue import Catalogue, classify, utc_now

IGNORED_DIRS = frozenset({
    ".git", ".svn", "@eadir", "#recycle", "$recycle.bin",
    "system volume information", ".trash", ".trashes",
})
BATCH = 64
PROFILE_DELAY = {"quiet": 0.10, "balanced": 0.035, "fast": 0.005}
KIND_SELECTION = {
    "film": {"films", "television", "anime", "home-videos"},
    "ebook": {"ebooks"},
    "audiobook": {"audiobooks"},
    "music": {"music"},
    "comic": {"comics"},
    "photo": {"photographs"},
    "other": {"other"},
}


def selected_for_library(kind: str, media_types: list[str]) -> bool:
    # Subtitles and metadata are tracked with their media. Video files cannot
    # be split into film, series and anime by extension alone; matching comes later.
    return kind == "sidecar" or bool(KIND_SELECTION.get(kind, set()) & set(media_types))


class Scanner:
    def __init__(self, catalogue: Catalogue):
        self.catalogue = catalogue
        self._lock = threading.RLock()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_job: int | None = None

    def _start(self, job_id: int, library: dict) -> int:
        self._pause.clear()
        self._active_job = job_id
        self._thread = threading.Thread(
            target=self._run, args=(job_id, library),
            name="tabarc-readonly-scanner", daemon=True
        )
        self._thread.start()
        return job_id

    def start(self, library_id: int, resume_id: int | None = None) -> int:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise ValueError("A scan is already running. Pause it before starting another.")
            library = self.catalogue.library(library_id)
            if not library:
                raise ValueError("Library does not exist.")
            if resume_id is not None:
                job = self.catalogue.job(resume_id)
                if not job or job["state"] != "paused" or job["library_id"] != library_id:
                    raise ValueError("Only a paused job for this library can be resumed.")
                job_id = resume_id
                # Recheck from the root after a pause or restart. Previously
                # indexed files are updated in place rather than duplicated.
                self.catalogue.update_job(job_id, state="running", seen=0,
                                          changed=0, errors=0, message="")
            else:
                job_id = self.catalogue.new_job(library_id)
            return self._start(job_id, library)

    def pause(self, job_id: int):
        with self._lock:
            if job_id != self._active_job or not self._thread or not self._thread.is_alive():
                raise ValueError("That job is not running.")
            self._pause.set()

    def shutdown(self):
        with self._lock:
            thread = self._thread
            if thread and thread.is_alive():
                self._pause.set()
        # Don't hold the worker lock while joining. Its finally block needs
        # the same lock to clear the active-job marker.
        if thread and thread.is_alive():
            thread.join(timeout=5)

    def _run(self, job_id: int, library: dict):
        root = Path(library["root"])
        started = utc_now()
        seen = changed = errors = 0
        pending: list[tuple[str, str, int, int, float]] = []
        last_error = ""
        delay = PROFILE_DELAY.get(library.get("scan_profile", "balanced"), 0.035)

        def flush():
            nonlocal pending
            if pending:
                self.catalogue.upsert_batch(library["id"], pending)
                pending = []
            self.catalogue.update_job(job_id, seen=seen, changed=changed,
                                      errors=errors, message=last_error)

        try:
            stack = [root]
            while stack:
                if self._pause.is_set():
                    flush()
                    self.catalogue.update_job(job_id, state="paused",
                                              message="Paused; the next run rechecks this library incrementally.")
                    return
                directory = stack.pop()
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if self._pause.is_set():
                                break
                            try:
                                if entry.is_symlink():
                                    continue
                                if entry.is_dir(follow_symlinks=False):
                                    if entry.name.lower() not in IGNORED_DIRS:
                                        stack.append(Path(entry.path))
                                    continue
                                if not entry.is_file(follow_symlinks=False):
                                    continue
                                kind = classify(entry.name)
                                if not selected_for_library(kind, library["media_types"]):
                                    continue
                                stat = entry.stat(follow_symlinks=False)
                                relative = str(Path(entry.path).relative_to(root))
                                pending.append((relative, kind,
                                                stat.st_size, stat.st_mtime_ns, utc_now()))
                                seen += 1
                                changed += 1  # Indexed entries, not claims of altered media.
                                if len(pending) >= BATCH:
                                    flush()
                                    time.sleep(delay)
                            except OSError as exc:
                                errors += 1
                                last_error = f"Could not inspect {entry.name}: {exc.strerror or exc}"
                except OSError as exc:
                    errors += 1
                    last_error = f"Could not read {directory.name}: {exc.strerror or exc}"
            if self._pause.is_set():
                flush()
                self.catalogue.update_job(job_id, state="paused",
                                          message="Paused; the next run rechecks this library incrementally.")
                return
            flush()
            if errors == 0:
                self.catalogue.finalise_scan(library["id"], started)
            self.catalogue.update_job(
                job_id, state="completed" if not errors else "completed_with_errors",
                seen=seen, changed=changed, errors=errors, message=last_error
            )
        except Exception as exc:
            # Leave old index entries untouched on failure. The error belongs
            # in the job history rather than being swallowed by the thread.
            self.catalogue.update_job(job_id, state="failed", seen=seen,
                                      changed=changed, errors=errors + 1,
                                      message=f"{type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                if self._active_job == job_id:
                    self._active_job = None
