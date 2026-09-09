import json
import time

import venvdoctor.outdated as outdated_mod
from venvdoctor.outdated import _is_outdated, _ver_key, check_outdated


def test_basic_numeric_ordering():
    assert _ver_key("1.2.3") < _ver_key("1.2.4")
    assert _ver_key("1.9.9") < _ver_key("2.0")
    assert _ver_key("1.0") < _ver_key("1.0.1")


def test_prerelease_sorts_before_final():
    assert _ver_key("1.0.0a1") < _ver_key("1.0.0")
    assert _ver_key("1.0.0b1") < _ver_key("1.0.0")
    assert _ver_key("1.0.0rc1") < _ver_key("1.0.0")


def test_prerelease_stage_ordering():
    assert _ver_key("1.0.0a1") < _ver_key("1.0.0b1")
    assert _ver_key("1.0.0b1") < _ver_key("1.0.0rc1")
    assert _ver_key("1.0.0rc1") < _ver_key("1.0.0rc2")


def test_dev_release_sorts_before_prerelease():
    assert _ver_key("1.0.0.dev1") < _ver_key("1.0.0a1")


def test_postrelease_sorts_after_final():
    assert _ver_key("1.0.0") < _ver_key("1.0.0.post1")
    assert _ver_key("1.0.0.post1") < _ver_key("1.0.0.post2")


def test_is_outdated_true_for_newer_latest():
    assert _is_outdated("1.0.0", "1.0.1") is True
    assert _is_outdated("1.0.0rc1", "1.0.0") is True


def test_is_outdated_false_for_same_or_older():
    assert _is_outdated("1.0.1", "1.0.1") is False
    assert _is_outdated("1.0.1", "1.0.0") is False


def test_unparseable_version_falls_back_to_string_inequality():
    # Garbage input shouldn't raise; it should degrade gracefully.
    assert _is_outdated("not-a-version", "not-a-version") is False


def _patch_cache_path(monkeypatch, tmp_path):
    monkeypatch.setattr(outdated_mod, "_CACHE_PATH", tmp_path / "pypi_cache.json")


def test_check_outdated_finds_newer_version(monkeypatch, tmp_path):
    _patch_cache_path(monkeypatch, tmp_path)
    monkeypatch.setattr(outdated_mod, "_pypi_latest", lambda name: ("2.0.0", False))

    packages = [{"name": "demo", "version": "1.0.0", "size_bytes": 10}]
    results, failed = check_outdated(packages, use_cache=False)

    assert failed == []
    assert results == [{"name": "demo", "installed": "1.0.0", "latest": "2.0.0", "size_bytes": 10}]


def test_check_outdated_reports_lookup_failures_separately(monkeypatch, tmp_path):
    _patch_cache_path(monkeypatch, tmp_path)
    monkeypatch.setattr(outdated_mod, "_pypi_latest", lambda name: (None, True))

    packages = [{"name": "flaky", "version": "1.0.0", "size_bytes": 10}]
    results, failed = check_outdated(packages, use_cache=False)

    assert results == []
    assert failed == ["flaky"]


def test_check_outdated_writes_and_reuses_cache(monkeypatch, tmp_path):
    _patch_cache_path(monkeypatch, tmp_path)
    call_count = {"n": 0}

    def fake_pypi_latest(name):
        call_count["n"] += 1
        return "2.0.0", False

    monkeypatch.setattr(outdated_mod, "_pypi_latest", fake_pypi_latest)
    packages = [{"name": "demo", "version": "1.0.0", "size_bytes": 10}]

    check_outdated(packages, use_cache=True)
    assert call_count["n"] == 1
    assert json.loads(outdated_mod._CACHE_PATH.read_text())["demo"]["latest"] == "2.0.0"

    # Second run should hit the cache instead of calling _pypi_latest again.
    results, _ = check_outdated(packages, use_cache=True)
    assert call_count["n"] == 1
    assert results[0]["latest"] == "2.0.0"


def test_check_outdated_ignores_expired_cache_entry(monkeypatch, tmp_path):
    _patch_cache_path(monkeypatch, tmp_path)
    outdated_mod._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    stale = {"demo": {"latest": "1.5.0", "checked_at": time.time() - outdated_mod._CACHE_TTL - 1}}
    outdated_mod._CACHE_PATH.write_text(json.dumps(stale))

    monkeypatch.setattr(outdated_mod, "_pypi_latest", lambda name: ("2.0.0", False))
    packages = [{"name": "demo", "version": "1.0.0", "size_bytes": 10}]

    results, _ = check_outdated(packages, use_cache=True)
    assert results[0]["latest"] == "2.0.0"
