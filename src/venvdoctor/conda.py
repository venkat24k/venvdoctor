"""
conda.py
--------
Support for reading package metadata directly from an environment's
``conda-meta/`` directory.

This covers packages conda installed without a pip-style dist-info
(e.g. compiled libraries like openssl, mkl, sqlite, icu) that
importlib.metadata can never see, since they aren't Python
distributions at all. VenvDoctor's dist-info-based scan already picks
up most user-facing Python packages in a conda environment (conda-forge
builds typically ship dist-info alongside them) — this module fills the
gap for everything else.

Public API
----------
is_conda_env(venv_path)                  -> bool
get_conda_packages(venv_path)            -> list[dict]
get_conda_package_detail(venv_path, name) -> dict | None
"""

from __future__ import annotations

import json
from pathlib import Path


def is_conda_env(venv_path: Path) -> bool:
    """Return True if *venv_path* looks like a conda environment."""
    return (Path(venv_path) / "conda-meta").is_dir()


def normalize_name(name: str) -> str:
    """Normalize a package name for cross-source (pip vs conda) matching."""
    return name.lower().replace("_", "-")


def get_conda_packages(venv_path: Path) -> list[dict]:
    """
    Return info for every package recorded in conda-meta.

    Each entry: {name, version, size_bytes, deps, channel, build}.
    size_bytes is computed by summing the actual on-disk size of each
    file the package installed (per conda-meta's "files" list), not the
    record's cached "size" field, which reflects compressed download
    size and can differ significantly from installed size.
    """
    venv_path = Path(venv_path)
    meta_dir = venv_path / "conda-meta"
    if not meta_dir.is_dir():
        return []

    packages: list[dict] = []
    for record_path in sorted(meta_dir.glob("*.json")):
        parsed = _parse_record(venv_path, record_path)
        if parsed is not None:
            packages.append(parsed)
    return packages


def get_conda_package_detail(venv_path: Path, package_name: str) -> dict | None:
    """Return the conda-meta record for *package_name*, or None if absent."""
    target = normalize_name(package_name)
    for pkg in get_conda_packages(venv_path):
        if normalize_name(pkg["name"]) == target:
            return pkg
    return None


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _parse_record(venv_path: Path, record_path: Path) -> dict | None:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    name = record.get("name")
    if not name:
        return None

    size_bytes = 0
    for rel_file in record.get("files", []):
        try:
            file_path = venv_path / rel_file
            if file_path.is_file():
                size_bytes += file_path.stat().st_size
        except OSError:
            pass

    return {
        "name": name,
        "version": record.get("version", "unknown"),
        "size_bytes": size_bytes,
        "deps": [_dep_name(d) for d in record.get("depends", []) if _dep_name(d)],
        "channel": record.get("channel", ""),
        "build": record.get("build", ""),
    }


def _dep_name(dep_spec: str) -> str:
    """Extract the package name from a conda dependency spec, e.g. "numpy >=1.19,<2.0"."""
    parts = dep_spec.split()
    return parts[0] if parts else ""
