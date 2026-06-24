"""
scanner.py
----------
Multi-virtual-environment scanner for VenvDoctor.

Public API
----------
find_venvs(root)                 -> list[Path]
scan_all(root)                   -> list[VenvSummary]
duplicate_packages(summaries)    -> dict[str, list[dict]]
cleanup_candidates(summaries, days_old) -> list[dict]
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from .package_analyzer import get_package_sizes
from .formatters import human_size


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class VenvSummary(dict):
    """Dict subclass holding per-venv scan results."""

    @property
    def path(self) -> Path:
        return Path(self["path"])

    @property
    def total_bytes(self) -> int:
        return self["total_bytes"]

    @property
    def packages(self) -> list[dict]:
        return self["packages"]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_VENV_MARKERS = frozenset([
    "pyvenv.cfg",            # created by venv / virtualenv
    "conda-meta",            # Conda environments
])


def find_venvs(root: str | Path, max_depth: int = 5) -> list[Path]:
    """
    Recursively search *root* for virtual environment directories.

    Returns a list of absolute Paths, each pointing to a venv root.
    """
    root = Path(root).expanduser().resolve()
    found: list[Path] = []
    _walk(root, root, 0, max_depth, found)
    return found


def _walk(
    current: Path,
    root: Path,
    depth: int,
    max_depth: int,
    found: list[Path],
) -> None:
    if depth > max_depth:
        return

    try:
        entries = list(current.iterdir())
    except PermissionError:
        return

    # Check if *current* itself is a venv
    names = {e.name for e in entries}
    if _VENV_MARKERS & names:
        found.append(current)
        return  # don't recurse into venvs

    for entry in entries:
        if not entry.is_dir():
            continue
        # Skip common non-project dirs to keep scanning fast
        if entry.name in {
            "__pycache__", ".git", ".hg", ".svn",
            "node_modules", ".tox", ".mypy_cache",
            "dist", "build", ".eggs",
        }:
            continue
        _walk(entry, root, depth + 1, max_depth, found)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_all(root: str | Path) -> list[VenvSummary]:
    """
    Find all virtual environments under *root* and return summary data.

    Returns a list of VenvSummary dicts sorted by total_bytes descending.
    """
    venvs = find_venvs(root)
    summaries: list[VenvSummary] = []

    for venv_path in venvs:
        try:
            packages = get_package_sizes(venv_path)
        except Exception as exc:
            packages = []
            error = str(exc)
        else:
            error = None

        total_bytes = sum(p["size_bytes"] for p in packages)
        last_modified = _dir_mtime(venv_path)

        summaries.append(VenvSummary(
            path=str(venv_path),
            total_bytes=total_bytes,
            total_size_human=human_size(total_bytes),
            package_count=len(packages),
            packages=packages,
            last_modified=last_modified,
            last_modified_days_ago=_days_ago(last_modified),
            error=error,
        ))

    summaries.sort(key=lambda s: s["total_bytes"], reverse=True)
    return summaries


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def duplicate_packages(
    summaries: list[VenvSummary],
) -> dict[str, list[dict]]:
    """
    Find packages that appear across multiple environments.

    Returns
    -------
    dict mapping package_name -> [
        {"venv": str, "version": str, "size_bytes": int}, ...
    ]
    Only packages present in 2+ environments are included.
    """
    index: dict[str, list[dict]] = {}

    for summary in summaries:
        for pkg in summary["packages"]:
            name = pkg["name"]
            if name not in index:
                index[name] = []
            index[name].append({
                "venv": summary["path"],
                "version": pkg.get("version", "unknown"),
                "size_bytes": pkg["size_bytes"],
            })

    return {name: entries for name, entries in index.items() if len(entries) > 1}


# ---------------------------------------------------------------------------
# Cleanup recommendations
# ---------------------------------------------------------------------------

def cleanup_candidates(
    summaries: list[VenvSummary],
    days_old: int = 90,
) -> list[dict]:
    """
    Return environments that haven't been touched in *days_old* days.

    Returns list of dicts sorted by total_bytes descending.
    """
    cutoff = days_old * 86400   # seconds
    now = time.time()
    candidates = []

    for summary in summaries:
        mtime = summary.get("last_modified", 0)
        age_seconds = now - mtime if mtime else 0
        if age_seconds >= cutoff:
            candidates.append({
                "path": summary["path"],
                "total_bytes": summary["total_bytes"],
                "total_size_human": summary["total_size_human"],
                "days_ago": int(age_seconds // 86400),
                "package_count": summary["package_count"],
            })

    candidates.sort(key=lambda c: c["total_bytes"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dir_mtime(path: Path) -> float:
    """Return the most-recent modification time of any file in *path*."""
    try:
        # pyvenv.cfg is a good proxy
        cfg = path / "pyvenv.cfg"
        if cfg.exists():
            return cfg.stat().st_mtime
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _days_ago(mtime: float) -> int:
    if not mtime:
        return -1
    return int((time.time() - mtime) // 86400)