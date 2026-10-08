"""Shared fixtures. Every library here is a throwaway folder under tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest


def make_library(root: Path) -> None:
    """A small, deliberately untidy library."""
    movie = root / "Movies" / "Arrival (2016)"
    movie.mkdir(parents=True)
    (movie / "Arrival (2016).mkv").write_bytes(b"x" * 10)
    (movie / "movie.nfo").write_text("<movie/>")
    (movie / "._Arrival (2016).mkv").write_bytes(b"appledouble")
    book = root / "Books" / "Author"
    book.mkdir(parents=True)
    (book / "Title.epub").write_bytes(b"y" * 5)
    (root / "_review").mkdir()
    (root / "_review" / "skipped.mkv").write_bytes(b"z")
    (root / "#snapshot" / "daily").mkdir(parents=True)
    (root / "#snapshot" / "daily" / "copy.mkv").write_bytes(b"s")
    (root / "notes.txt").write_text("not media")


def write_config(path: Path, db: Path, roots: list[Path], extra: str = "") -> Path:
    roots_toml = ", ".join(f'"{r}"' for r in roots)
    path.write_text(f'[database]\npath = "{db}"\n[libraries]\nroots = [{roots_toml}]\n{extra}')
    return path


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    make_library(lib)
    return lib
