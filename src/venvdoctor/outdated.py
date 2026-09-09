"""
outdated.py
-----------
Check for outdated packages by querying the PyPI JSON API.

Public API
----------
check_outdated(packages, verbose=False, use_cache=True) -> (list[dict], list[str])
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_PYPI_URL = "https://pypi.org/pypi/{name}/json"
_TIMEOUT  = 5    # seconds per request
_WORKERS  = 8    # concurrent requests
_RETRIES  = 1    # extra attempts after a transient network failure
_RETRY_DELAY = 0.5  # seconds between retries

_CACHE_PATH = Path.home() / ".venvdoctor" / "pypi_cache.json"
_CACHE_TTL  = 24 * 3600  # how long a cached "latest version" stays valid


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def check_outdated(
    packages: list[dict],
    verbose: bool = False,
    use_cache: bool = True,
) -> tuple[list[dict], list[str]]:
    """
    Compare installed package versions against the latest on PyPI.

    Results are cached per package name (not per installed version, since
    "latest on PyPI" doesn't depend on what's installed locally) at
    ~/.venvdoctor/pypi_cache.json for _CACHE_TTL seconds, so repeated runs
    don't re-query PyPI for packages checked recently. Only the main
    thread touches the cache dict, so no locking is needed despite the
    concurrent lookups.

    Returns
    -------
    (results, failed) where:
      results: dicts for packages with a newer version available
        {name, installed, latest, size_bytes}, sorted by name.
      failed: names of packages whose PyPI lookup failed after retries
        (e.g. network/timeout issues) — NOT the same as "up to date".
    """
    cache = _load_cache() if use_cache else {}
    now = time.time()

    def _check(pkg: dict) -> dict | None:
        name      = pkg["name"]
        installed = pkg.get("version", "")
        if not installed or installed == "unknown":
            return None

        key = name.lower()
        cached = cache.get(key)
        if cached and (now - cached.get("checked_at", 0)) < _CACHE_TTL:
            return {
                "name": name, "installed": installed, "latest": cached.get("latest"),
                "size_bytes": pkg["size_bytes"], "lookup_failed": False, "from_cache": True,
            }

        latest, lookup_failed = _pypi_latest(name)
        return {
            "name": name, "installed": installed, "latest": latest,
            "size_bytes": pkg["size_bytes"], "lookup_failed": lookup_failed, "from_cache": False,
        }

    results: list[dict] = []
    failed: list[str] = []
    cache_updates: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_check, pkg): pkg for pkg in packages}
        done = 0
        total = len(packages)
        for future in as_completed(futures):
            done += 1
            if verbose:
                print(f"\r  Checking {done}/{total}…", end="", flush=True)

            outcome = future.result()
            if outcome is None:
                continue
            if outcome["lookup_failed"]:
                failed.append(outcome["name"])
                continue
            if outcome["latest"] is None:
                continue

            if not outcome["from_cache"]:
                cache_updates[outcome["name"].lower()] = {
                    "latest": outcome["latest"],
                    "checked_at": now,
                }

            if _is_outdated(outcome["installed"], outcome["latest"]):
                results.append({
                    "name":      outcome["name"],
                    "installed": outcome["installed"],
                    "latest":    outcome["latest"],
                    "size_bytes": outcome["size_bytes"],
                })

    if verbose:
        print()  # newline after progress

    if use_cache and cache_updates:
        cache.update(cache_updates)
        _save_cache(cache)

    results.sort(key=lambda r: r["name"].lower())
    failed.sort(key=str.lower)
    return results, failed


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass  # caching is a best-effort optimization, not required for correctness

def _pypi_latest(name: str) -> tuple[str | None, bool]:
    """
    Return (latest_version, lookup_failed) for *name* on PyPI.

    A 404 (package not on PyPI) is a normal, non-failing outcome and
    returns (None, False). A network/timeout/decoding error retries once
    before being reported as a failed lookup: (None, True).
    """
    url = _PYPI_URL.format(name=name)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "VenvDoctor/1.0 (https://github.com/venkat24k/venvdoctor)"},
    )

    for attempt in range(_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                data = json.loads(resp.read())
            return data.get("info", {}).get("version"), False
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, False
            # Other HTTP errors (5xx, rate limiting) are worth retrying.
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            pass

        if attempt < _RETRIES:
            time.sleep(_RETRY_DELAY)

    return None, True


def _is_outdated(installed: str, latest: str) -> bool:
    """Return True if *latest* sorts after *installed* under PEP 440-ish rules."""
    try:
        return _ver_key(latest) > _ver_key(installed)
    except Exception:
        return installed != latest


# A pragmatic PEP 440 subset: epoch, release segments, pre-release
# (a/b/rc), post-release, and dev-release. Anything else (local versions,
# odd formats) still parses — it just falls back to a release-only key.
_VERSION_RE = re.compile(
    r"""
    ^\s*
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:[-_.]?(?P<pre_l>a|b|c|rc|alpha|beta|pre|preview)[-_.]?(?P<pre_n>[0-9]*))?
    (?:[-_.]?(?:post|rev|r)[-_.]?(?P<post_n>[0-9]*))?
    (?:[-_.]?dev[-_.]?(?P<dev_n>[0-9]*))?
    """,
    re.VERBOSE | re.IGNORECASE,
)

_PRE_RANK = {
    "a": 0, "alpha": 0,
    "b": 1, "beta": 1,
    "c": 2, "rc": 2, "pre": 2, "preview": 2,
}


def _ver_key(version: str) -> tuple:
    """
    Build a sortable key approximating PEP 440 ordering:
      X.devN < X.aN < X.bN < X.rcN < X < X.postN
    """
    match = _VERSION_RE.match(version.strip())
    if not match:
        return (0, (0,), 2, 0, 0, 0, 0)

    epoch = int(match.group("epoch") or 0)
    release = tuple(int(p) for p in match.group("release").split("."))

    is_dev = match.group("dev_n") is not None
    is_pre = match.group("pre_l") is not None
    is_post = match.group("post_n") is not None

    if is_dev and not is_pre:
        stage, pre_rank, pre_num = 0, 0, 0
    elif is_pre:
        stage = 1
        pre_rank = _PRE_RANK.get(match.group("pre_l").lower(), 0)
        pre_num = int(match.group("pre_n") or 0)
    elif is_post:
        stage, pre_rank, pre_num = 3, 0, 0
    else:
        stage, pre_rank, pre_num = 2, 0, 0

    post_num = int(match.group("post_n") or 0) if is_post else 0
    dev_num = int(match.group("dev_n") or 0) if is_dev else 0

    return (epoch, release, stage, pre_rank, pre_num, post_num, dev_num)