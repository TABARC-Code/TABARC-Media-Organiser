"""Load and validate configuration.

Only reads files. Never writes to the media roots.

Validation is strict on purpose: a typo in a key name is rejected rather
than silently ignored, because a silently ignored exclusion list on a NAS
can mean scanning a snapshot folder ten times over.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


# These mirror the packaged default.toml. A test keeps the two in step.
#
# Exclusions cover common NAS and OS system folders. Names that don't
# exist on a given box are harmless. Matching is case-insensitive.
DEFAULT_EXCLUDE_DIRS = [
    "_review",
    ".Trash", ".Trashes", "$RECYCLE.BIN", "System Volume Information", "lost+found",
    "@eaDir", "#recycle", "#snapshot",          # Synology
    "@Recycle", "@Recently-Snapshot",           # QNAP
    ".snapshot", ".snapshots", ".AppleDouble",
]
DEFAULT_MEDIA_EXTENSIONS = [
    ".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".m2ts", ".webm", ".wmv", ".mpg", ".mpeg",
    ".epub", ".pdf", ".mobi", ".azw3",
    ".mp3", ".flac", ".m4a",
    ".cbz", ".cbr",
]
DEFAULT_SIDECAR_EXTENSIONS = [
    ".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".opf",
    ".jpg", ".jpeg", ".png", ".webp",
]
DEFAULT_PROBE_VIDEO = True
DEFAULT_PROBE_TIMEOUT_SECONDS = 30

_KNOWN_SECTIONS = {
    "database": {"path"},
    "libraries": {"roots"},
    "inventory": {
        "exclude_dirs", "media_extensions", "sidecar_extensions",
        "probe_video", "probe_timeout_seconds",
    },
    "providers": {"contact", "language", "offline", "enabled", "max_age_days"},
}

KNOWN_PROVIDERS = ("wikidata", "tvmaze", "openlibrary")
DEFAULT_PROVIDERS_ENABLED = list(KNOWN_PROVIDERS)
DEFAULT_PROVIDER_LANGUAGE = "en-gb"
DEFAULT_MAX_AGE_DAYS = 30


@dataclass(frozen=True)
class InventoryConfig:
    exclude_dirs: frozenset[str]          # stored lower-case
    media_extensions: frozenset[str]      # lower-case, leading dot
    sidecar_extensions: frozenset[str]    # lower-case, leading dot
    probe_video: bool
    probe_timeout_seconds: int


@dataclass(frozen=True)
class ProvidersConfig:
    contact: str              # sent in the User-Agent. Required before any lookup.
    language: str
    offline: bool
    enabled: tuple[str, ...]
    max_age_days: int


def default_providers() -> ProvidersConfig:
    return ProvidersConfig(
        contact="",
        language=DEFAULT_PROVIDER_LANGUAGE,
        offline=False,
        enabled=tuple(DEFAULT_PROVIDERS_ENABLED),
        max_age_days=DEFAULT_MAX_AGE_DAYS,
    )


@dataclass(frozen=True)
class Config:
    database_path: Path
    roots: tuple[Path, ...]
    inventory: InventoryConfig
    providers: ProvidersConfig = field(default_factory=default_providers)


def default_inventory() -> InventoryConfig:
    """Inventory settings used when the config omits [inventory]."""
    return _build_inventory({})


def default_config_text() -> str:
    """The packaged default.toml, as text."""
    return resources.files("tabarc_media.config").joinpath("default.toml").read_text("utf-8")


def write_initial_config(path: Path, roots: list[str]) -> Config:
    """Write a starter config to *path* and return it, validated.

    Refuses to overwrite an existing file. The text is validated before
    it lands, so a bad root (relative, nested, duplicated) never leaves a
    half-written config behind.
    """
    path = Path(path).expanduser()
    if path.exists():
        raise ConfigError(f"Config already exists, not overwriting: {path}")

    text = default_config_text()
    if roots:
        # JSON string escapes are valid TOML basic-string escapes.
        listed = ", ".join(json.dumps(r) for r in roots)
        if "\nroots = []\n" not in text:
            raise ConfigError("Packaged default.toml has no 'roots = []' line to fill in")
        text = text.replace("\nroots = []\n", f"\nroots = [{listed}]\n", 1)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, "utf-8")
    try:
        cfg = load_config(tmp)
    except ConfigError:
        tmp.unlink()
        raise
    os.replace(tmp, path)
    return cfg


# ---------------------------------------------------------------- helpers

def _str_list(value, key: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of strings")
    return value


def _extension(raw: str, key: str) -> str:
    ext = raw.strip().lower()
    if not ext or ext == ".":
        raise ConfigError(f"{key} contains an empty extension")
    return ext if ext.startswith(".") else "." + ext


def _norm(p: str) -> Path:
    return Path(os.path.normpath(Path(p).expanduser()))


def _check_keys(raw: dict) -> None:
    for section, value in raw.items():
        if section not in _KNOWN_SECTIONS:
            raise ConfigError(
                f"Unknown section [{section}]. Known: {', '.join(sorted(_KNOWN_SECTIONS))}"
            )
        if not isinstance(value, dict):
            raise ConfigError(f"[{section}] must be a table")
        unknown = set(value) - _KNOWN_SECTIONS[section]
        if unknown:
            raise ConfigError(f"Unknown key(s) in [{section}]: {', '.join(sorted(unknown))}")


def _build_providers(raw: dict) -> ProvidersConfig:
    contact = raw.get("contact", "")
    if not isinstance(contact, str):
        raise ConfigError("providers.contact must be a string")
    language = raw.get("language", DEFAULT_PROVIDER_LANGUAGE)
    if not isinstance(language, str) or not language.strip():
        raise ConfigError("providers.language must be a non-empty string such as 'en-gb'")
    offline = raw.get("offline", False)
    if not isinstance(offline, bool):
        raise ConfigError("providers.offline must be true or false")
    enabled = _str_list(raw.get("enabled", DEFAULT_PROVIDERS_ENABLED), "providers.enabled")
    unknown = [e for e in enabled if e not in KNOWN_PROVIDERS]
    if unknown:
        raise ConfigError(
            f"Unknown provider(s) in providers.enabled: {', '.join(unknown)}. "
            f"Known: {', '.join(KNOWN_PROVIDERS)}"
        )
    age = raw.get("max_age_days", DEFAULT_MAX_AGE_DAYS)
    if isinstance(age, bool) or not isinstance(age, int) or age < 0:
        raise ConfigError("providers.max_age_days must be a whole number, 0 or more")
    return ProvidersConfig(
        contact=contact.strip(),
        language=language.strip().lower(),
        offline=offline,
        enabled=tuple(dict.fromkeys(enabled)),
        max_age_days=age,
    )


def _build_inventory(inv: dict) -> InventoryConfig:
    exclude = _str_list(inv.get("exclude_dirs", DEFAULT_EXCLUDE_DIRS), "inventory.exclude_dirs")
    media = {
        _extension(e, "inventory.media_extensions")
        for e in _str_list(inv.get("media_extensions", DEFAULT_MEDIA_EXTENSIONS),
                           "inventory.media_extensions")
    }
    sidecar = {
        _extension(e, "inventory.sidecar_extensions")
        for e in _str_list(inv.get("sidecar_extensions", DEFAULT_SIDECAR_EXTENSIONS),
                           "inventory.sidecar_extensions")
    }
    overlap = media & sidecar
    if overlap:
        raise ConfigError(
            f"Extensions listed as both media and sidecar: {', '.join(sorted(overlap))}"
        )

    probe = inv.get("probe_video", DEFAULT_PROBE_VIDEO)
    if not isinstance(probe, bool):
        raise ConfigError("inventory.probe_video must be true or false")

    timeout = inv.get("probe_timeout_seconds", DEFAULT_PROBE_TIMEOUT_SECONDS)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigError("inventory.probe_timeout_seconds must be a positive whole number")

    return InventoryConfig(
        exclude_dirs=frozenset(d.lower() for d in exclude),
        media_extensions=frozenset(media),
        sidecar_extensions=frozenset(sidecar),
        probe_video=probe,
        probe_timeout_seconds=timeout,
    )


# ---------------------------------------------------------------- public

def load_config(path: Path) -> Config:
    """Load a TOML config file and validate everything Stage 1 uses."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config file is not valid TOML: {exc}") from exc

    _check_keys(raw)

    db = raw.get("database", {})
    if not isinstance(db.get("path"), str) or not db["path"].strip():
        raise ConfigError("Missing [database] path")
    db_path = _norm(db["path"])
    if not db_path.is_absolute():
        raise ConfigError(f"[database] path must be absolute (~ is allowed): {db_path}")

    raw_roots = _str_list(raw.get("libraries", {}).get("roots", []), "libraries.roots")
    roots = tuple(_norm(p) for p in raw_roots)
    for root in roots:
        if not root.is_absolute():
            raise ConfigError(f"Library root must be an absolute path: {root}")

    # Duplicate or nested roots would record the same file twice under
    # different keys, and later stages would try to rename it twice.
    for i, a in enumerate(roots):
        for b in roots[i + 1:]:
            if a == b:
                raise ConfigError(f"Library root listed twice: {a}")
            if a in b.parents or b in a.parents:
                raise ConfigError(f"Library roots overlap: {a} and {b}")

    for root in roots:
        if root == db_path or root in db_path.parents:
            raise ConfigError(
                f"Database path {db_path} is inside library root {root}. "
                "Keep the catalogue on local disk, away from the media."
            )

    return Config(
        database_path=db_path,
        roots=roots,
        inventory=_build_inventory(raw.get("inventory", {})),
        providers=_build_providers(raw.get("providers", {})),
    )
