import json

from venvdoctor.conda import get_conda_package_detail, get_conda_packages, is_conda_env
from venvdoctor.package_analyzer import get_dependency_tree, get_package_detail, get_package_sizes


def _make_conda_env(tmp_path):
    env_dir = tmp_path / "conda_env"
    (env_dir / "conda-meta").mkdir(parents=True)
    (env_dir / "Lib" / "site-packages").mkdir(parents=True)
    return env_dir


def _write_conda_record(env_dir, name, version, files_and_sizes, depends=()):
    """Write a conda-meta record plus the files it lists, at the given sizes."""
    files = []
    for rel_path, size in files_and_sizes:
        full = env_dir / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(b"x" * size)
        files.append(rel_path)

    record = {
        "name": name,
        "version": version,
        "build": "0",
        "channel": "conda-forge",
        "files": files,
        "depends": list(depends),
    }
    record_path = env_dir / "conda-meta" / f"{name}-{version}-0.json"
    record_path.write_text(json.dumps(record))


def test_is_conda_env_detects_conda_meta(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    assert is_conda_env(env_dir) is True

    not_conda = tmp_path / "plain_venv"
    not_conda.mkdir()
    assert is_conda_env(not_conda) is False


def test_get_conda_packages_sums_file_sizes(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    _write_conda_record(
        env_dir, "openssl", "3.2.0",
        [("Library/bin/libssl.dll", 500), ("Library/bin/libcrypto.dll", 300)],
    )

    packages = get_conda_packages(env_dir)

    assert len(packages) == 1
    assert packages[0]["name"] == "openssl"
    assert packages[0]["size_bytes"] == 800


def test_get_conda_packages_parses_dependency_names(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    _write_conda_record(
        env_dir, "numpy", "1.26.4",
        [("Lib/site-packages/numpy/__init__.py", 10)],
        depends=["python >=3.9,<3.10.0a0", "libblas * *mkl"],
    )

    detail = get_conda_package_detail(env_dir, "numpy")
    assert detail["deps"] == ["python", "libblas"]


def test_get_conda_package_detail_missing_returns_none(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    assert get_conda_package_detail(env_dir, "does-not-exist") is None


def test_get_package_sizes_includes_conda_only_packages(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    # A conda-only package with no dist-info (e.g. a compiled library).
    _write_conda_record(env_dir, "sqlite", "3.45.0", [("Library/bin/sqlite3.dll", 1200)])

    packages = get_package_sizes(env_dir)
    by_name = {p["name"]: p for p in packages}

    assert "sqlite" in by_name
    assert by_name["sqlite"]["size_bytes"] == 1200


def test_get_package_sizes_does_not_double_count_dist_info_package(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    site_packages = env_dir / "Lib" / "site-packages"

    # Real dist-info for numpy...
    dist_info = site_packages / "numpy-1.26.4.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text("Metadata-Version: 2.1\nName: numpy\nVersion: 1.26.4\n")
    pkg_file = site_packages / "numpy" / "core.py"
    pkg_file.parent.mkdir()
    pkg_file.write_bytes(b"x" * 999)
    (dist_info / "RECORD").write_text("numpy/core.py,,999\n")

    # ...and a conda-meta record for the SAME package (as conda-forge does).
    _write_conda_record(env_dir, "numpy", "1.26.4", [("Lib/site-packages/numpy/core.py", 999)])

    packages = get_package_sizes(env_dir)
    numpy_entries = [p for p in packages if p["name"].lower() == "numpy"]

    # Only the dist-info-derived entry should be present, not a second
    # conda-derived "numpy" entry.
    assert len(numpy_entries) == 1


def test_get_package_detail_falls_back_to_conda_record(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    _write_conda_record(env_dir, "mkl", "2024.0.0", [("Library/bin/mkl_core.dll", 5000)])

    info = get_package_detail("mkl", env_dir)
    assert info["name"] == "mkl"
    assert info["size_bytes"] == 5000
    assert "conda-forge" in info["summary"]


def test_get_dependency_tree_includes_conda_packages(tmp_path):
    env_dir = _make_conda_env(tmp_path)
    _write_conda_record(
        env_dir, "libblas", "3.9.0", [("Library/bin/libblas.dll", 100)],
        depends=["libopenblas"],
    )

    tree = get_dependency_tree(env_dir)
    assert "libblas" in tree
    assert tree["libblas"]["deps"] == ["libopenblas"]
