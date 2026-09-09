"""
scanner.py
----------
Multi-virtual-environment scanner for VenvDoctor.

Public API
----------
find_venvs(root)                 -> list[Path]
scan_all(root)                   -> list[VenvSummary]
duplicate_packages(summaries)    -> dict[str, list[dict]]
compare_venvs(venv_a, venv_b)    -> dict
cleanup_candidates(summaries, days_old) -> list[dict]
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .formatters import human_size
from .package_analyzer import get_package_sizes

_SCAN_WORKERS = 8  # concurrent per-venv scans; scanning is I/O-bound (stat calls)

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

_DEFAULT_IGNORE_DIRS = frozenset([
    "__pycache__", ".git", ".hg", ".svn",
    "node_modules", ".tox", ".mypy_cache",
    "dist", "build", ".eggs",
])


def find_venvs(
    root: str | Path,
    max_depth: int = 5,
    extra_ignore: tuple[str, ...] = (),
) -> list[Path]:
    """
    Recursively search *root* for virtual environment directories.

    *extra_ignore* names (e.g. from a .venvdoctor.toml config) are skipped
    in addition to the built-in noise directories.

    Returns a list of absolute Paths, each pointing to a venv root.
    """
    root = Path(root).expanduser().resolve()
    ignore_dirs = _DEFAULT_IGNORE_DIRS | frozenset(extra_ignore)
    found: list[Path] = []
    _walk(root, 0, max_depth, ignore_dirs, found)
    return found


def _walk(
    current: Path,
    depth: int,
    max_depth: int,
    ignore_dirs: frozenset[str],
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
        if entry.name in ignore_dirs:
            continue
        _walk(entry, depth + 1, max_depth, ignore_dirs, found)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_one(venv_path: Path) -> VenvSummary:
    try:
        packages = get_package_sizes(venv_path)
    except Exception as exc:
        packages = []
        error = str(exc)
    else:
        error = None

    total_bytes = sum(p["size_bytes"] for p in packages)
    last_modified = _dir_mtime(venv_path)

    return VenvSummary(
        path=str(venv_path),
        total_bytes=total_bytes,
        total_size_human=human_size(total_bytes),
        package_count=len(packages),
        packages=packages,
        last_modified=last_modified,
        last_modified_days_ago=_days_ago(last_modified),
        error=error,
    )


def scan_all(root: str | Path, extra_ignore: tuple[str, ...] = ()) -> list[VenvSummary]:
    """
    Find all virtual environments under *root* and return summary data.

    Each venv is scanned concurrently (scanning is I/O-bound: mostly file
    stat calls), so wall-clock time scales with the slowest venv rather
    than the sum of all of them.

    Returns a list of VenvSummary dicts sorted by total_bytes descending.
    """
    venvs = find_venvs(root, extra_ignore=extra_ignore)
    if not venvs:
        return []

    with ThreadPoolExecutor(max_workers=min(_SCAN_WORKERS, len(venvs))) as pool:
        summaries = list(pool.map(_scan_one, venvs))

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
# Environment comparison
# ---------------------------------------------------------------------------

def compare_venvs(venv_a: str | Path, venv_b: str | Path) -> dict:
    """
    Compare the installed packages of two virtual environments.

    Raises
    ------
    FileNotFoundError  if either path is not a valid virtual environment
    (propagated from get_package_sizes).
    """
    venv_a = Path(venv_a)
    venv_b = Path(venv_b)

    pkgs_a = {p["name"]: p for p in get_package_sizes(venv_a)}
    pkgs_b = {p["name"]: p for p in get_package_sizes(venv_b)}

    names_a = set(pkgs_a)
    names_b = set(pkgs_b)

    only_in_a = [
        {
            "name": n,
            "version": pkgs_a[n].get("version", "unknown"),
            "size_bytes": pkgs_a[n]["size_bytes"],
        }
        for n in sorted(names_a - names_b)
    ]
    only_in_b = [
        {
            "name": n,
            "version": pkgs_b[n].get("version", "unknown"),
            "size_bytes": pkgs_b[n]["size_bytes"],
        }
        for n in sorted(names_b - names_a)
    ]

    common_same_version: list[dict] = []
    common_version_mismatch: list[dict] = []
    for name in sorted(names_a & names_b):
        version_a = pkgs_a[name].get("version", "unknown")
        version_b = pkgs_b[name].get("version", "unknown")
        entry = {
            "name": name,
            "version_a": version_a,
            "version_b": version_b,
            "size_bytes_a": pkgs_a[name]["size_bytes"],
            "size_bytes_b": pkgs_b[name]["size_bytes"],
        }
        if version_a == version_b:
            common_same_version.append(entry)
        else:
            common_version_mismatch.append(entry)

    return {
        "venv_a": str(venv_a),
        "venv_b": str(venv_b),
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "common_same_version": common_same_version,
        "common_version_mismatch": common_version_mismatch,
        "total_bytes_a": sum(p["size_bytes"] for p in pkgs_a.values()),
        "total_bytes_b": sum(p["size_bytes"] for p in pkgs_b.values()),
    }


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