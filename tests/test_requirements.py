import sys

import pytest

from venvdoctor.requirements import (
    compute_dependency_drift,
    find_declared_dependencies,
    parse_pyproject_toml,
    parse_requirements_txt,
)


def test_parse_requirements_txt_strips_specifiers_extras_and_markers(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join([
            "numpy>=1.26,<2.0",
            "requests[security]==2.31.0",
            "black ; python_version >= '3.8'",
            "# a comment line",
            "",
            "-r other.txt",
            "git+https://github.com/example/pkg.git#egg=pkg",
            "./local-package",
            "pandas",
        ])
    )

    names = parse_requirements_txt(req)
    assert names == ["numpy", "requests", "black", "pandas"]


def test_parse_requirements_txt_missing_file_returns_empty(tmp_path):
    assert parse_requirements_txt(tmp_path / "nope.txt") == []


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_parse_pyproject_toml_reads_project_dependencies(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["numpy>=1.26", "pandas"]\n'
    )
    assert parse_pyproject_toml(pyproject) == ["numpy", "pandas"]


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_parse_pyproject_toml_reads_poetry_dependencies_excluding_python(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.poetry.dependencies]\npython = "^3.10"\nrequests = "^2.31"\n'
    )
    assert parse_pyproject_toml(pyproject) == ["requests"]


def test_find_declared_dependencies_dedupes_across_both_files(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\npandas\n")
    if sys.version_info >= (3, 11):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["numpy", "requests"]\n'
        )
        names, sources = find_declared_dependencies(tmp_path)
        assert set(n.lower() for n in names) == {"numpy", "pandas", "requests"}
        assert len(sources) == 2
    else:
        names, sources = find_declared_dependencies(tmp_path)
        assert set(n.lower() for n in names) == {"numpy", "pandas"}


def test_compute_dependency_drift_flags_orphans_and_missing():
    tree = {
        "pandas": {"version": "2.2.1", "size_bytes": 100, "deps": ["numpy", "pytz"]},
        "numpy": {"version": "1.26.0", "size_bytes": 200, "deps": []},
        "pytz": {"version": "2024.1", "size_bytes": 10, "deps": []},
        "black": {"version": "24.0", "size_bytes": 50, "deps": []},  # not declared, no deps of it
    }
    declared = ["pandas", "requests"]  # requests declared but not installed

    drift = compute_dependency_drift(tree, declared)

    # black is installed but unreachable from "pandas" -> orphaned.
    assert drift["orphaned"] == ["black"]
    # requests is declared but missing from installed packages.
    assert drift["missing"] == ["requests"]


def test_compute_dependency_drift_transitive_deps_are_not_orphaned():
    tree = {
        "pandas": {"version": "2.2.1", "size_bytes": 100, "deps": ["numpy"]},
        "numpy": {"version": "1.26.0", "size_bytes": 200, "deps": []},
    }
    drift = compute_dependency_drift(tree, declared=["pandas"])
    # numpy is a transitive dep of the declared "pandas" — must not be orphaned.
    assert drift["orphaned"] == []
    assert drift["missing"] == []
