"""
config.py
---------
Optional config file (.venvdoctor.toml) providing defaults for common CLI
options, so routine invocations don't have to repeat the same flags.

Looked up in order: ./.venvdoctor.toml (current directory), then
~/.venvdoctor.toml (user home). The first one found is used — no merging
across both.

Recognized keys
----------------
top          int        — default --top
days_old     int        — default --days-old for `scan --cleanup`
ignore_dirs  list[str]  — extra directory names for `scan`/`compare` to skip

Requires Python 3.11+ (tomllib); silently returns {} on older versions or
when no config file exists, so this feature degrades to "no defaults"
rather than failing.

Public API
----------
load_config() -> dict
"""

from __future__ import annotations

from pathlib import Path

CONFIG_FILENAME = ".venvdoctor.toml"


def _config_search_paths() -> list[Path]:
    return [Path.cwd() / CONFIG_FILENAME, Path.home() / CONFIG_FILENAME]


def load_config() -> dict:
    """Return the first valid .venvdoctor.toml found, or {} if none."""
    try:
        import tomllib
    except ModuleNotFoundError:
        return {}

    for path in _config_search_paths():
        if not path.is_file():
            continue
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return {}
    return {}
