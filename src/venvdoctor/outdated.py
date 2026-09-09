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
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

_PYPI_URL = "https://pypi.org/pypi/{name}/json"
_TIMEOUT  = 5    # seconds per request
_WORKERS  = 8    # concurrent requests
_RETRIES  = 1    # extra attempts after a transient network failure
_RETRY_DELAY = 0.5  # seconds between retries


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def check_outdated(
    packages: list[dict],
    verbose: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    Compare installed package versions against the latest on PyPI.

    Returns
    -------
    (results, failed) where:
      results: dicts for packages with a newer version available
        {name, installed, latest, size_bytes}, sorted by name.
      failed: names of packages whose PyPI lookup failed after retries
        (e.g. network/timeout issues) — NOT the same as "up to date".
    """
    results: list[dict] = []
    failed: list[str] = []

    def _check(pkg: dict) -> tuple[dict | None, str | None]:
        name      = pkg["name"]
        installed = pkg.get("version", "")
        if not installed or installed == "unknown":
            return None, None

        latest, lookup_failed = _pypi_latest(name)
        if lookup_failed:
            return None, name
        if latest is None:
            return None, None

        if _is_outdated(installed, latest):
            return {
                "name":      name,
                "installed": installed,
                "latest":    latest,
                "size_bytes": pkg["size_bytes"],
            }, None
        return None, None

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(_check, pkg): pkg for pkg in packages}
        done = 0
        total = len(packages)
        for future in as_completed(futures):
            done += 1
            if verbose:
                print(f"\r  Checking {done}/{total}…", end="", flush=True)
            result, failed_name = future.result()
            if result:
                results.append(result)
            if failed_name:
                failed.append(failed_name)

    if verbose:
        print()  # newline after progress

    results.sort(key=lambda r: r["name"].lower())
    failed.sort(key=str.lower)
    return results, failed


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

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