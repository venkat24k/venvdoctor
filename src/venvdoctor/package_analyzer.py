"""
package_analyzer.py
-------------------
Core analysis engine for VenvDoctor.

Supports analyzing:
  - The currently active virtual environment (default)
  - Any arbitrary virtual environment via a path

Public API
----------
get_package_sizes(venv_path=None)       -> list[PackageInfo]
get_package_detail(name, venv_path=None) -> dict
"""

from __future__ import annotations

import importlib.metadata
import sys
from importlib.metadata import PathDistribution
from pathlib import Path

from .conda import get_conda_package_detail, get_conda_packages, is_conda_env, normalize_name

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class PackageInfo(dict):
    """A plain dict with typed helper properties for convenience."""

    @property
    def name(self) -> str:
        return self["name"]

    @property
    def version(self) -> str:
        return self.get("version", "unknown")

    @property
    def size_bytes(self) -> int:
        return self["size_bytes"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _site_packages(venv_path: Path) -> list[Path]:
    """
    Return candidate site-packages directories inside *venv_path*.

    Handles Windows (Lib/site-packages) and Unix (lib/pythonX.Y/site-packages).
    """
    candidates: list[Path] = []

    # Windows layout
    win = venv_path / "Lib" / "site-packages"
    if win.is_dir():
        candidates.append(win)

    # Unix layout  (lib/python3.x/site-packages)
    lib = venv_path / "lib"
    if lib.is_dir():
        for child in lib.iterdir():
            sp = child / "site-packages"
            if sp.is_dir():
                candidates.append(sp)

    return candidates


def _distributions_for_venv(venv_path: Path):
    """
    Yield importlib.metadata distributions discovered inside *venv_path*.
    """
    site_pkgs = _site_packages(venv_path)
    if not site_pkgs:
        raise FileNotFoundError(
            f"No site-packages directory found under: {venv_path}\n"
            "Make sure the path points to a valid Python virtual environment."
        )

    for sp in site_pkgs:
        yield from importlib.metadata.distributions(path=[str(sp)])


def _calc_dist_size(dist: PathDistribution) -> int:
    """Return total byte size of files belonging to *dist*."""
    if not dist.files:
        return 0

    total = 0
    for f in dist.files:
        try:
            path = dist.locate_file(f)
            if path.exists() and path.is_file():
                total += path.stat().st_size
        except (OSError, ValueError):
            pass
    return total


def _get_requires(dist: PathDistribution) -> list[str]:
    """Return a cleaned list of direct dependency names."""
    raw = dist.metadata.get_all("Requires-Dist") or []
    names: list[str] = []
    for req in raw:
        # strip extras / version specifiers  e.g. "numpy>=1.0 ; extra=='test'"
        name = req.split(";")[0].split(">=")[0].split("<=")[0]
        name = name.split("!=")[0].split("==")[0].split("~=")[0]
        name = name.split("[")[0].strip()
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_package_sizes(venv_path: Path | None = None) -> list[PackageInfo]:
    """
    Return a list of PackageInfo dicts for all installed packages.

    Parameters
    ----------
    venv_path:
        Path to a virtual environment root.  When *None* the currently active
        environment (``sys.prefix``) is used.
    """
    if venv_path is None:
        dists = importlib.metadata.distributions()
        env_root = Path(sys.prefix)
    else:
        venv_path = Path(venv_path)
        dists = _distributions_for_venv(venv_path)
        env_root = venv_path

    package_sizes: dict[str, PackageInfo] = {}

    for dist in dists:
        name = dist.metadata.get("Name", "Unknown")
        version = dist.metadata.get("Version", "unknown")
        size = _calc_dist_size(dist)

        if name not in package_sizes:
            package_sizes[name] = PackageInfo(
                name=name,
                version=version,
                size_bytes=size,
            )
        else:
            # Keep the larger entry (handles editable install duplicates)
            if size > package_sizes[name]["size_bytes"]:
                package_sizes[name] = PackageInfo(
                    name=name,
                    version=version,
                    size_bytes=size,
                )

    _merge_conda_packages(package_sizes, env_root)

    return list(package_sizes.values())


def _merge_conda_packages(package_sizes: dict[str, PackageInfo], env_root: Path) -> None:
    """
    Add conda-only packages (no pip-style dist-info) into *package_sizes*
    in place, skipping any name already covered by a dist-info entry.
    """
    if not is_conda_env(env_root):
        return

    known = {normalize_name(n) for n in package_sizes}
    for conda_pkg in get_conda_packages(env_root):
        if normalize_name(conda_pkg["name"]) in known:
            continue
        package_sizes[conda_pkg["name"]] = PackageInfo(
            name=conda_pkg["name"],
            version=conda_pkg["version"],
            size_bytes=conda_pkg["size_bytes"],
        )


def get_package_detail(
    package_name: str,
    venv_path: Path | None = None,
) -> dict:
    """
    Return detailed info for a single package by name.

    Raises
    ------
    KeyError  if the package is not found.
    """
    if venv_path is None:
        dists = importlib.metadata.distributions()
        env_root = Path(sys.prefix)
    else:
        venv_path = Path(venv_path)
        dists = _distributions_for_venv(venv_path)
        env_root = venv_path

    for dist in dists:
        name = dist.metadata.get("Name", "Unknown")
        if name.lower() != package_name.lower():
            continue

        size = _calc_dist_size(dist)
        requires = _get_requires(dist)
        location = str(dist.locate_file(""))

        return {
            "name": name,
            "version": dist.metadata.get("Version", "unknown"),
            "size_bytes": size,
            "location": location,
            "summary": dist.metadata.get("Summary", ""),
            "home_page": dist.metadata.get("Home-page", ""),
            "license": dist.metadata.get("License", ""),
            "dependencies": requires,
        }

    conda_pkg = get_conda_package_detail(env_root, package_name) if is_conda_env(env_root) else None
    if conda_pkg is not None:
        return {
            "name": conda_pkg["name"],
            "version": conda_pkg["version"],
            "size_bytes": conda_pkg["size_bytes"],
            "location": str(env_root),
            "summary": f"Conda package (channel: {conda_pkg['channel'] or 'unknown'})",
            "home_page": "",
            "license": "",
            "dependencies": conda_pkg["deps"],
        }

    raise KeyError(f"Package '{package_name}' not found.")


def get_dependency_tree(
    venv_path: Path | None = None,
) -> dict[str, dict]:
    """
    Build a dependency tree mapping each package to its direct deps.

    Returns
    -------
    dict mapping package name -> {version, size_bytes, deps: [str]}
    """
    if venv_path is None:
        dists = list(importlib.metadata.distributions())
        env_root = Path(sys.prefix)
    else:
        venv_path = Path(venv_path)
        dists = list(_distributions_for_venv(venv_path))
        env_root = venv_path

    tree: dict[str, dict] = {}
    for dist in dists:
        name = dist.metadata.get("Name", "Unknown")
        if name in tree:
            continue
        tree[name] = {
            "version": dist.metadata.get("Version", "unknown"),
            "size_bytes": _calc_dist_size(dist),
            "deps": _get_requires(dist),
        }

    if is_conda_env(env_root):
        known = {normalize_name(n) for n in tree}
        for conda_pkg in get_conda_packages(env_root):
            if normalize_name(conda_pkg["name"]) in known:
                continue
            tree[conda_pkg["name"]] = {
                "version": conda_pkg["version"],
                "size_bytes": conda_pkg["size_bytes"],
                "deps": conda_pkg["deps"],
            }

    return tree