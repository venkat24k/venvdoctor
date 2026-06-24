"""
outdated.py
-----------
Check for outdated packages by querying the PyPI JSON API.

Public API
----------
check_outdated(packages, verbose) -> list[dict]
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

_PYPI_URL = "https://pypi.org/pypi/{name}/json"
_TIMEOUT  = 5   # seconds per request
_WORKERS  = 8   # concurrent requests


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def check_outdated(
    packages: list[dict],
    verbose: bool = False,
) -> list[dict]:
    """
    Compare installed package versions against the latest on PyPI.

    Returns
    -------
    List of dicts for packages that have newer versions available:
      {name, installed, latest, size_bytes}
    Sorted by name.
    """
    results: list[dict] = []

    def _check(pkg: dict) -> Optional[dict]:
        name      = pkg["name"]
        installed = pkg.get("version", "")
        if not installed or installed == "unknown":
            return None

        latest = _pypi_latest(name)
        if latest is None:
            return None

        if _is_outdated(installed, latest):
            return {
                "name":      name,
                "installed": installed,
                "latest":    latest,
                "size_bytes": pkg["size_bytes"],
            }
        return None

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_check, pkg): pkg for pkg in packages}
        done = 0
        total = len(packages)
        for future in as_completed(futures):
            done += 1
            if verbose:
                print(f"\r  Checking {done}/{total}…", end="", flush=True)
            result = future.result()
            if result:
                results.append(result)

    if verbose:
        print()  # newline after progress

    results.sort(key=lambda r: r["name"].lower())
    return results


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _pypi_latest(name: str) -> Optional[str]:
    """Return the latest stable release version from PyPI, or None."""
    url = _PYPI_URL.format(name=name)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "VenvDoctor/1.0 (https://github.com/yourusername/venvdoctor)"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read())
        return data.get("info", {}).get("version")
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, OSError):
        return None


def _is_outdated(installed: str, latest: str) -> bool:
    """
    Simple version comparison.

    Uses tuple comparison after splitting on "." and padding with zeros.
    Handles most PEP 440 version strings but falls back to string comparison
    for pre-releases / local versions.
    """
    try:
        inst_tuple  = _ver_tuple(installed)
        latest_tuple = _ver_tuple(latest)
        return latest_tuple > inst_tuple
    except Exception:
        return installed != latest


def _ver_tuple(version: str) -> tuple[int, ...]:
    """Convert "1.2.3" → (1, 2, 3). Non-numeric parts become 0."""
    parts = []
    for part in version.split(".")[:4]:
        # strip pre-release suffixes like "1a2", "1b3", "1rc1"
        numeric = ""
        for ch in part:
            if ch.isdigit():
                numeric += ch
            else:
                break
        parts.append(int(numeric) if numeric else 0)
    # pad to length 4
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)