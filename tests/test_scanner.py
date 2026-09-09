import time

from venvdoctor.scanner import cleanup_candidates, duplicate_packages, find_venvs


def _make_venv(root, name):
    venv_dir = root / name
    (venv_dir / "Lib" / "site-packages").mkdir(parents=True)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n")
    return venv_dir


def test_find_venvs_locates_pyvenv_cfg_dirs(tmp_path):
    v1 = _make_venv(tmp_path / "project_a", "venv")
    v2 = _make_venv(tmp_path / "project_b", ".venv")

    found = find_venvs(tmp_path)

    assert v1.resolve() in found
    assert v2.resolve() in found
    assert len(found) == 2


def test_find_venvs_does_not_recurse_into_a_found_venv(tmp_path):
    venv_dir = _make_venv(tmp_path, "venv")
    # Simulate a nested site-packages that also happens to look venv-like;
    # it must NOT be reported separately since we stop recursing once a
    # venv root is identified.
    nested = venv_dir / "Lib" / "site-packages" / "some_pkg"
    nested.mkdir(parents=True, exist_ok=True)

    found = find_venvs(tmp_path)
    assert found == [venv_dir.resolve()]


def test_find_venvs_skips_noise_directories(tmp_path):
    (tmp_path / "node_modules" / "pyvenv.cfg").parent.mkdir(parents=True)
    (tmp_path / "node_modules" / "pyvenv.cfg").write_text("")

    found = find_venvs(tmp_path)
    assert found == []


def test_find_venvs_skips_extra_ignore_dirs(tmp_path):
    venv_dir = _make_venv(tmp_path / "archive", "venv")

    found_without_ignore = find_venvs(tmp_path)
    assert venv_dir.resolve() in found_without_ignore

    found_with_ignore = find_venvs(tmp_path, extra_ignore=("archive",))
    assert found_with_ignore == []


def test_duplicate_packages_only_returns_packages_in_2plus_envs():
    summaries = [
        {
            "path": "/envs/a",
            "packages": [
                {"name": "numpy", "version": "1.26.0", "size_bytes": 100},
                {"name": "onlyinA", "version": "1.0", "size_bytes": 5},
            ],
        },
        {
            "path": "/envs/b",
            "packages": [
                {"name": "numpy", "version": "1.26.0", "size_bytes": 100},
            ],
        },
    ]

    dupes = duplicate_packages(summaries)

    assert "numpy" in dupes
    assert "onlyinA" not in dupes
    assert len(dupes["numpy"]) == 2


def test_cleanup_candidates_filters_by_age():
    now = time.time()
    summaries = [
        {
            "path": "/envs/old",
            "total_bytes": 1000,
            "total_size_human": "1000.00 B",
            "package_count": 1,
            "last_modified": now - 200 * 86400,
        },
        {
            "path": "/envs/new",
            "total_bytes": 500,
            "total_size_human": "500.00 B",
            "package_count": 1,
            "last_modified": now - 1 * 86400,
        },
    ]

    candidates = cleanup_candidates(summaries, days_old=90)

    assert len(candidates) == 1
    assert candidates[0]["path"] == "/envs/old"
