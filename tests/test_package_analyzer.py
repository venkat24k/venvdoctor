from venvdoctor.package_analyzer import get_dependency_tree, get_package_detail, get_package_sizes


def _make_dist(site_packages, name, version, size_bytes, requires=()):
    """
    Create a minimal, importlib.metadata-readable dist-info directory
    under *site_packages*, plus one data file of exactly *size_bytes*.
    """
    dist_info = site_packages / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True)

    metadata_lines = [
        "Metadata-Version: 2.1",
        f"Name: {name}",
        f"Version: {version}",
        "Summary: A test package",
    ]
    for req in requires:
        metadata_lines.append(f"Requires-Dist: {req}")
    (dist_info / "METADATA").write_text("\n".join(metadata_lines) + "\n")

    pkg_dir = site_packages / name
    pkg_dir.mkdir()
    data_file = pkg_dir / "data.bin"
    data_file.write_bytes(b"x" * size_bytes)

    # Only list the data file, so the calculated dist size is exactly
    # size_bytes and not inflated by METADATA/RECORD's own size on disk.
    record_lines = [f"{name}/data.bin,,{size_bytes}"]
    (dist_info / "RECORD").write_text("\n".join(record_lines) + "\n")


def _make_venv(tmp_path):
    venv_dir = tmp_path / "venv"
    site_packages = venv_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True)
    return venv_dir, site_packages


def test_get_package_sizes_reads_real_distributions(tmp_path):
    venv_dir, site_packages = _make_venv(tmp_path)
    _make_dist(site_packages, "demo-pkg", "1.0", size_bytes=1024)

    packages = get_package_sizes(venv_dir)

    assert len(packages) == 1
    assert packages[0]["name"] == "demo-pkg"
    assert packages[0]["version"] == "1.0"
    assert packages[0]["size_bytes"] == 1024


def test_get_package_sizes_missing_venv_raises(tmp_path):
    empty_dir = tmp_path / "not_a_venv"
    empty_dir.mkdir()
    try:
        get_package_sizes(empty_dir)
        raised = False
    except FileNotFoundError:
        raised = True
    assert raised


def test_get_package_detail_returns_dependencies(tmp_path):
    venv_dir, site_packages = _make_venv(tmp_path)
    _make_dist(
        site_packages, "demo-pkg", "1.0", size_bytes=10,
        requires=["numpy>=1.0", "requests[security]; extra=='full'"],
    )

    info = get_package_detail("demo-pkg", venv_dir)

    assert info["name"] == "demo-pkg"
    assert "numpy" in info["dependencies"]
    assert "requests" in info["dependencies"]


def test_get_package_detail_unknown_package_raises_keyerror(tmp_path):
    venv_dir, site_packages = _make_venv(tmp_path)
    _make_dist(site_packages, "demo-pkg", "1.0", size_bytes=10)

    try:
        get_package_detail("does-not-exist", venv_dir)
        raised = False
    except KeyError:
        raised = True
    assert raised


def test_get_dependency_tree_maps_names_to_deps(tmp_path):
    venv_dir, site_packages = _make_venv(tmp_path)
    _make_dist(site_packages, "pkg-a", "1.0", size_bytes=10, requires=["pkg-b"])
    _make_dist(site_packages, "pkg-b", "1.0", size_bytes=20)

    tree = get_dependency_tree(venv_dir)

    assert set(tree.keys()) == {"pkg-a", "pkg-b"}
    assert tree["pkg-a"]["deps"] == ["pkg-b"]
    assert tree["pkg-b"]["size_bytes"] == 20
