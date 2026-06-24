"""
tree.py
-------
Dependency tree rendering for VenvDoctor.

Public API
----------
print_tree(tree_data, top_n, show_size)
largest_deps(tree_data, top_n)
"""

from __future__ import annotations

from .formatters import human_size


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def print_tree(
    tree_data: dict[str, dict],
    top_n: int = 0,
    show_size: bool = True,
    indent: str = "  ",
) -> None:
    """
    Print a dependency tree for all (or top *top_n*) packages.

    tree_data is the dict returned by package_analyzer.get_dependency_tree().

    Example output
    --------------
    pandas  (2.2.1)  43.21 MB
    ├── numpy
    ├── pytz
    └── python-dateutil
    """
    # Normalise names for lookup (lowercased)
    name_map: dict[str, str] = {k.lower(): k for k in tree_data}

    packages = list(tree_data.items())

    if top_n > 0:
        packages = sorted(
            packages,
            key=lambda kv: kv[1]["size_bytes"],
            reverse=True,
        )[:top_n]
    else:
        packages = sorted(packages, key=lambda kv: kv[0].lower())

    for pkg_name, info in packages:
        size_str = f"  {human_size(info['size_bytes'])}" if show_size else ""
        print(f"\n{pkg_name}  ({info['version']}){size_str}")

        deps = info.get("deps", [])
        if not deps:
            print(f"{indent}(no dependencies)")
            continue

        for i, dep in enumerate(deps):
            connector = "└──" if i == len(deps) - 1 else "├──"
            # Try to resolve version from tree
            canonical = name_map.get(dep.lower())
            if canonical and canonical in tree_data:
                dep_ver = tree_data[canonical]["version"]
                dep_size = (
                    f"  {human_size(tree_data[canonical]['size_bytes'])}"
                    if show_size else ""
                )
                print(f"{indent}{connector} {canonical} ({dep_ver}){dep_size}")
            else:
                print(f"{indent}{connector} {dep}")


def largest_deps(
    tree_data: dict[str, dict],
    top_n: int = 10,
) -> list[dict]:
    """
    Return the *top_n* packages sorted by their **total impact**:
    own size + sum of unique transitive dependency sizes.

    Returns a list of dicts:
      {name, version, own_bytes, total_bytes, deps: [str]}
    """
    # Build a resolved total for each package (BFS, avoid cycles)
    results = []

    for pkg_name, info in tree_data.items():
        visited: set[str] = set()
        total = _recursive_size(pkg_name, tree_data, visited)
        results.append({
            "name": pkg_name,
            "version": info["version"],
            "own_bytes": info["size_bytes"],
            "total_bytes": total,
            "deps": info.get("deps", []),
        })

    results.sort(key=lambda r: r["total_bytes"], reverse=True)
    return results[:top_n]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _recursive_size(
    name: str,
    tree: dict[str, dict],
    visited: set[str],
) -> int:
    if name in visited:
        return 0
    visited.add(name)

    info = tree.get(name)
    if info is None:
        # Try case-insensitive lookup
        for k in tree:
            if k.lower() == name.lower():
                info = tree[k]
                name = k
                break
        if info is None:
            return 0

    total = info["size_bytes"]
    for dep in info.get("deps", []):
        total += _recursive_size(dep, tree, visited)
    return total