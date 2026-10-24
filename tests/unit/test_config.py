from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tabarc_media.config.loader import (
    ConfigError, default_inventory, default_providers, load_config,
)

REPO = Path(__file__).resolve().parents[2]


def _cfg(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def _db(tmp_path: Path) -> str:
    return f'[database]\npath = "{tmp_path / "local" / "c.sqlite3"}"\n'


def test_default_toml_matches_loader_defaults():
    # Stops config/default.toml and the code drifting apart.
    packaged = REPO / "src" / "tabarc_media" / "config" / "default.toml"
    with packaged.open("rb") as fh:
        raw = tomllib.load(fh)
    cfg = load_config(packaged)
    assert cfg.inventory == default_inventory()
    assert cfg.providers == default_providers()
    assert raw["libraries"]["roots"] == []


def test_missing_database_path(tmp_path):
    with pytest.raises(ConfigError, match="database"):
        load_config(_cfg(tmp_path, "[libraries]\nroots = []\n"))


def test_relative_database_path(tmp_path):
    with pytest.raises(ConfigError, match="absolute"):
        load_config(_cfg(tmp_path, '[database]\npath = "rel/c.sqlite3"\n'))


def test_relative_root_rejected(tmp_path):
    with pytest.raises(ConfigError, match="absolute"):
        load_config(_cfg(tmp_path, _db(tmp_path) + '[libraries]\nroots = ["relative/path"]\n'))


def test_roots_as_string_rejected(tmp_path):
    # A bare string would otherwise be iterated character by character.
    with pytest.raises(ConfigError, match="list of strings"):
        load_config(_cfg(tmp_path, _db(tmp_path) + '[libraries]\nroots = "/mnt/media"\n'))


def test_duplicate_roots_rejected(tmp_path):
    body = _db(tmp_path) + '[libraries]\nroots = ["/mnt/a", "/mnt/a/"]\n'
    with pytest.raises(ConfigError, match="twice"):
        load_config(_cfg(tmp_path, body))


def test_nested_roots_rejected(tmp_path):
    body = _db(tmp_path) + '[libraries]\nroots = ["/mnt/media", "/mnt/media/TV"]\n'
    with pytest.raises(ConfigError, match="overlap"):
        load_config(_cfg(tmp_path, body))


def test_database_inside_root_rejected(tmp_path):
    body = '[database]\npath = "/mnt/media/cat.sqlite3"\n[libraries]\nroots = ["/mnt/media"]\n'
    with pytest.raises(ConfigError, match="inside library root"):
        load_config(_cfg(tmp_path, body))


def test_unknown_key_rejected(tmp_path):
    body = _db(tmp_path) + "[inventory]\nmedia_extension = ['.mkv']\n"
    with pytest.raises(ConfigError, match="Unknown key"):
        load_config(_cfg(tmp_path, body))


def test_unknown_section_rejected(tmp_path):
    with pytest.raises(ConfigError, match="Unknown section"):
        load_config(_cfg(tmp_path, _db(tmp_path) + "[invetory]\n"))


def test_bad_toml(tmp_path):
    with pytest.raises(ConfigError, match="TOML"):
        load_config(_cfg(tmp_path, "[database\n"))


def test_probe_flag_must_be_bool(tmp_path):
    body = _db(tmp_path) + '[inventory]\nprobe_video = "false"\n'
    with pytest.raises(ConfigError, match="true or false"):
        load_config(_cfg(tmp_path, body))


@pytest.mark.parametrize("value", ["0", "-5", "true", '"30"'])
def test_timeout_must_be_positive_int(tmp_path, value):
    body = _db(tmp_path) + f"[inventory]\nprobe_timeout_seconds = {value}\n"
    with pytest.raises(ConfigError, match="positive"):
        load_config(_cfg(tmp_path, body))


def test_extensions_normalised(tmp_path):
    body = _db(tmp_path) + '[inventory]\nmedia_extensions = ["MKV", ".Mp4"]\n'
    cfg = load_config(_cfg(tmp_path, body))
    assert cfg.inventory.media_extensions == {".mkv", ".mp4"}


def test_media_sidecar_overlap_rejected(tmp_path):
    body = _db(tmp_path) + ('[inventory]\nmedia_extensions = [".mkv", ".jpg"]\n'
                            'sidecar_extensions = [".jpg"]\n')
    with pytest.raises(ConfigError, match="both media and sidecar"):
        load_config(_cfg(tmp_path, body))


def test_exclusions_lower_cased(tmp_path):
    body = _db(tmp_path) + '[inventory]\nexclude_dirs = ["$RECYCLE.BIN"]\n'
    cfg = load_config(_cfg(tmp_path, body))
    assert cfg.inventory.exclude_dirs == {"$recycle.bin"}


def _cfg_text(tmp_path, extra=""):
    db = tmp_path / "db" / "c.sqlite3"
    return f'[database]\npath = "{db.as_posix()}"\n[libraries]\nroots = []\n{extra}'


def test_providers_section_is_read_and_normalised(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(_cfg_text(tmp_path, '[providers]\ncontact = "  me@example.org "\n'
                           'language = "EN-GB"\nenabled = ["tvmaze", "tvmaze"]\n'
                           'max_age_days = 7\n'))
    cfg = load_config(p)
    assert cfg.providers.contact == "me@example.org"
    assert cfg.providers.language == "en-gb"
    assert cfg.providers.enabled == ("tvmaze",)
    assert cfg.providers.max_age_days == 7
    assert cfg.providers.offline is False


@pytest.mark.parametrize("bad", [
    'enabled = ["imdb"]',
    'offline = "yes"',
    'max_age_days = -1',
    'max_age_days = true',
    'language = ""',
    'contact = 5',
    'nonsense = 1',
])
def test_bad_providers_values_are_rejected(tmp_path, bad):
    p = tmp_path / "c.toml"
    p.write_text(_cfg_text(tmp_path, f"[providers]\n{bad}\n"))
    with pytest.raises(ConfigError):
        load_config(p)
