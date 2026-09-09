"""
requirements.py
----------------
Cross-reference installed packages against declared dependencies
(requirements.txt / pyproject.toml) to flag drift: packages installed
but not reachable from anything declared ("orphaned"), and packages
declared but not installed ("missing").

"Orphaned" is computed via the full transitive-dependency closure of
the declared packages (using the dependency tree from
package_analyzer.get_dependency_tree), not a flat installed-vs-declared
diff — otherwise every indirect dependency (e.g. numpy pulled in by
pandas) would be falsely flagged as unused.

Public API
----------
find_declared_dependencies(project_root) -> (list[str], list[str])
compute_dependency_drift(tree, declared) -> dict
"""

from __future__ import annotations

from pathlib import Path

from .conda import normalize_name

_VERSION_OPERATORS = ("===", "==", ">=", "<=", "~=", "!=", ">", "<")


def _extract_name(requirement: str) -> str | None:
    """Best-effort extraction of a package name from one requirement entry."""
    line = requirement.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    if "://" in line or line.startswith(".") or line.startswith("/"):
        return None  # URL / local-path / VCS install — not a plain PyPI name

    line = line.split(";", 1)[0].strip()   # environment marker
    line = line.split("[", 1)[0].strip()   # extras

    for op in _VERSION_OPERATORS:
        if op in line:
            line = line.split(op, 1)[0].strip()
            break

    return line or None


def parse_requirements_txt(path: Path) -> list[str]:
    """Return declared package names from a requirements.txt-style file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []

    names = []
    for line in text.splitlines():
        name = _extract_name(line)
        if name:
            names.append(name)
    return names


def parse_pyproject_toml(path: Path) -> list[str]:
    """
    Return declared package names from [project.dependencies] and legacy
    [tool.poetry.dependencies]. Requires Python 3.11+ (tomllib); returns
    [] silently on older interpreters rather than raising.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        return []

    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    names = []
    for dep in data.get("project", {}).get("dependencies", []):
        name = _extract_name(dep)
        if name:
            names.append(name)

    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name in poetry_deps:
        if name.lower() != "python":
            names.append(name)

    return names


def find_declared_dependencies(project_root: Path) -> tuple[list[str], list[str]]:
    """
    Look for requirements.txt and/or pyproject.toml directly under
    *project_root* and return (declared_names, source_file_paths_used).
    """
    project_root = Path(project_root)
    names: list[str] = []
    sources: list[str] = []

    req_txt = project_root / "requirements.txt"
    if req_txt.is_file():
        names.extend(parse_requirements_txt(req_txt))
        sources.append(str(req_txt))

    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        found = parse_pyproject_toml(pyproject)
        if found:
            sources.append(str(pyproject))
        names.extend(found)

    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        key = normalize_name(name)
        if key not in seen:
            seen.add(key)
            deduped.append(name)
    return deduped, sources


def compute_dependency_drift(tree: dict[str, dict], declared: list[str]) -> dict:
    """
    Compare a dependency tree (from get_dependency_tree) against a list
    of directly declared package names.

    Returns
    -------
    {
      "orphaned": [str, ...],  # installed, not reachable from any declared package
      "missing":  [str, ...],  # declared, but not installed
    }
    """
    tree_by_norm = {normalize_name(name): name for name in tree}

    expected_norm: set[str] = set()
    queue = list(declared)
    while queue:
        current = queue.pop()
        norm = normalize_name(current)
        if norm in expected_norm:
            continue
        expected_norm.add(norm)
        canonical = tree_by_norm.get(norm)
        if canonical:
            queue.extend(tree[canonical].get("deps", []))

    installed_norm = set(tree_by_norm.keys())

    orphaned = sorted(tree_by_norm[n] for n in installed_norm - expected_norm)
    missing = sorted(name for name in declared if normalize_name(name) not in installed_norm)

    return {"orphaned": orphaned, "missing": missing}
