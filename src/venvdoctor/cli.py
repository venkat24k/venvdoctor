"""
cli.py
------
Command-line interface for VenvDoctor.

Usage
-----
venvdoctor                          # analyse current venv
venvdoctor --top 5                  # show only top-5 packages
venvdoctor --json                   # machine-readable JSON to stdout
venvdoctor --venv PATH              # analyse a different venv
venvdoctor --report out.json        # save JSON report to file
venvdoctor --report out.csv         # save CSV report to file
venvdoctor --html report.html       # save HTML dashboard
venvdoctor --tree                   # print dependency tree
venvdoctor --tree --top 5           # top-5 packages with their deps
venvdoctor --largest-deps           # packages sorted by total dep impact
venvdoctor --package numpy          # info about a single package
venvdoctor --outdated               # check PyPI for newer versions
venvdoctor scan PATH                # scan a directory for all venvs
venvdoctor scan PATH --duplicates   # find packages in multiple venvs
venvdoctor scan PATH --duplicates-html FILE    # save duplicate HTML dashboard
venvdoctor scan PATH --duplicates-report FILE  # save duplicate report (.json/.csv)
venvdoctor scan PATH --cleanup      # suggest old / large venvs to remove
venvdoctor compare VENV_A VENV_B    # diff installed packages between two venvs
venvdoctor --check-deps --project PATH  # compare installed vs requirements.txt/pyproject.toml

Defaults for --top, --days-old, and scan's ignored directories can be set
in a .venvdoctor.toml file (see config.py).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .config import load_config
from .formatters import human_size, to_csv, to_html, to_json
from .formatters_duplicates import to_duplicates_csv, to_duplicates_html, to_duplicates_json
from .package_analyzer import get_dependency_tree, get_package_detail, get_package_sizes
from .requirements import compute_dependency_drift, find_declared_dependencies
from .scanner import cleanup_candidates, compare_venvs, duplicate_packages, scan_all
from .tree import largest_deps, print_tree

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

DIVIDER = "=" * 50


def _header(title: str) -> None:
    print(f"\n{title}")
    print(DIVIDER)


def _resolve_venv(args) -> Path | None:
    """Return a Path for --venv, or None to use the current environment."""
    if not hasattr(args, "venv") or args.venv is None:
        return None
    venv_path = Path(args.venv)
    if not venv_path.exists():
        print(f"[error] Venv path does not exist: {venv_path}", file=sys.stderr)
        sys.exit(1)
    return venv_path


# ═══════════════════════════════════════════════════════════════════════════
# Sub-commands
# ═══════════════════════════════════════════════════════════════════════════

# ── analyse ─────────────────────────────────────────────────────────────────

def cmd_analyse(args) -> None:
    """Default analysis: summary + top packages."""
    venv_path = _resolve_venv(args)

    try:
        packages = get_package_sizes(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    total_bytes = sum(p["size_bytes"] for p in packages)
    env_path    = str(venv_path) if venv_path else sys.prefix
    py_ver      = sys.version.split()[0]
    py_exe      = sys.executable

    # ── JSON output ──
    if args.json:
        data = {
            "generated_at":      datetime.now().isoformat(timespec="seconds"),
            "python_version":    py_ver,
            "python_executable": py_exe,
            "environment_path":  env_path,
            "package_count":     len(packages),
            "environment_size":  human_size(total_bytes),
            "environment_size_bytes": total_bytes,
            "packages": sorted(
                [
                    {
                        "name":       p["name"],
                        "version":    p.get("version", "unknown"),
                        "size_bytes": p["size_bytes"],
                        "size_human": human_size(p["size_bytes"]),
                        "percentage": round(
                            (p["size_bytes"] / total_bytes * 100) if total_bytes else 0, 2
                        ),
                    }
                    for p in packages
                ],
                key=lambda x: x["size_bytes"],
                reverse=True,
            ),
        }
        print(to_json(data))
        return

    # ── Human-readable output ──
    print("\nVenvDoctor")
    print(DIVIDER)
    print(f"Python Version    : {py_ver}")
    print(f"Python Executable : {py_exe}")
    print(f"Environment Path  : {env_path}")
    print(f"Installed Packages: {len(packages)}")
    print(f"Environment Size  : {human_size(total_bytes)}")

    print("\nPackages:")
    for pkg in sorted(packages, key=lambda p: p["name"].lower()):
        print(f"  - {pkg['name']} ({pkg.get('version', '?')})")

    # Top packages
    sorted_pkgs = sorted(packages, key=lambda p: p["size_bytes"], reverse=True)
    top_n = min(args.top, len(sorted_pkgs))

    _header(f"Top {top_n} Packages By Disk Usage")
    for pkg in sorted_pkgs[:top_n]:
        pct      = (pkg["size_bytes"] / total_bytes * 100) if total_bytes else 0
        size_str = human_size(pkg["size_bytes"])
        print(
            f"  {pkg['name']:<30} "
            f"{size_str:>10}   "
            f"({pct:5.1f}%)"
        )


# ── report ──────────────────────────────────────────────────────────────────

def cmd_report(args) -> None:
    """Save a report file (json / csv / html)."""
    venv_path = _resolve_venv(args)
    out_path  = Path(args.report)
    suffix    = out_path.suffix.lower()

    try:
        packages = get_package_sizes(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    total_bytes = sum(p["size_bytes"] for p in packages)

    if suffix == ".csv":
        content = to_csv(packages, total_bytes)
        out_path.write_text(content, encoding="utf-8")
        print(f"CSV report saved to: {out_path}")

    elif suffix in (".json", ""):
        data = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "environment_path": str(venv_path) if venv_path else sys.prefix,
            "python_version": sys.version.split()[0],
            "environment_size_bytes": total_bytes,
            "environment_size": human_size(total_bytes),
            "package_count": len(packages),
            "packages": sorted(
                [
                    {
                        "name":       p["name"],
                        "version":    p.get("version", "unknown"),
                        "size_bytes": p["size_bytes"],
                        "size_human": human_size(p["size_bytes"]),
                    }
                    for p in packages
                ],
                key=lambda x: x["size_bytes"],
                reverse=True,
            ),
        }
        out_path.write_text(to_json(data), encoding="utf-8")
        print(f"JSON report saved to: {out_path}")

    elif suffix == ".html":
        _do_html(packages, total_bytes, venv_path, out_path, args)

    else:
        print(
            f"[error] Unknown report format '{suffix}'. Use .json, .csv, or .html",
            file=sys.stderr,
        )
        sys.exit(1)


# ── html ────────────────────────────────────────────────────────────────────

def cmd_html(args) -> None:
    """Generate an HTML dashboard and save to file."""
    venv_path = _resolve_venv(args)
    out_path  = Path(args.html)

    try:
        packages = get_package_sizes(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    total_bytes = sum(p["size_bytes"] for p in packages)
    _do_html(packages, total_bytes, venv_path, out_path, args)


def _do_html(packages, total_bytes, venv_path, out_path, args):
    report = {
        "generated_at":      datetime.now().isoformat(timespec="seconds"),
        "env_path":          str(venv_path) if venv_path else sys.prefix,
        "python_version":    sys.version.split()[0],
        "python_executable": sys.executable,
        "total_bytes":       total_bytes,
        "packages":          packages,
    }
    html = to_html(report)
    out_path.write_text(html, encoding="utf-8")
    print(f"HTML report saved to: {out_path}")


# ── tree ────────────────────────────────────────────────────────────────────

def cmd_tree(args) -> None:
    """Print dependency tree."""
    venv_path = _resolve_venv(args)

    try:
        tree_data = get_dependency_tree(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    _header("Dependency Tree")
    print_tree(tree_data, top_n=args.top, show_size=True)


# ── largest-deps ────────────────────────────────────────────────────────────

def cmd_largest_deps(args) -> None:
    """Show packages with largest total dependency footprint."""
    venv_path = _resolve_venv(args)

    try:
        tree_data = get_dependency_tree(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    results = largest_deps(tree_data, top_n=args.top)

    _header(f"Top {args.top} Packages By Total Dependency Impact")
    print(f"  {'Package':<30} {'Own Size':>12} {'Total Impact':>14}   Direct Deps")
    print(f"  {'-'*30} {'-'*12} {'-'*14}   {'-'*20}")

    for r in results:
        deps_preview = ", ".join(r["deps"][:4])
        if len(r["deps"]) > 4:
            deps_preview += f" … (+{len(r['deps'])-4})"
        print(
            f"  {r['name']:<30} "
            f"{human_size(r['own_bytes']):>12} "
            f"{human_size(r['total_bytes']):>14}   "
            f"{deps_preview}"
        )


# ── package ─────────────────────────────────────────────────────────────────

def cmd_package(args) -> None:
    """Show detailed info about a single package."""
    venv_path = _resolve_venv(args)

    try:
        info = get_package_detail(args.package, venv_path)
    except KeyError:
        print(f"[error] Package '{args.package}' not found.", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    _header(f"Package: {info['name']}")
    print(f"  Version    : {info['version']}")
    print(f"  Size       : {human_size(info['size_bytes'])} ({info['size_bytes']:,} bytes)")
    print(f"  Location   : {info['location']}")
    if info.get("summary"):
        print(f"  Summary    : {info['summary']}")
    if info.get("home_page"):
        print(f"  Home Page  : {info['home_page']}")
    if info.get("license"):
        print(f"  License    : {info['license']}")

    deps = info.get("dependencies", [])
    if deps:
        print(f"\n  Dependencies ({len(deps)}):")
        for dep in deps:
            print(f"    - {dep}")
    else:
        print("\n  No dependencies declared.")


# ── outdated ────────────────────────────────────────────────────────────────

def cmd_outdated(args) -> None:
    """Check PyPI for newer versions of installed packages."""
    from .outdated import check_outdated

    venv_path = _resolve_venv(args)

    try:
        packages = get_package_sizes(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    _header("Checking for Outdated Packages")
    print(f"  Querying PyPI for {len(packages)} packages (this may take a moment)…\n")

    results, failed = check_outdated(packages, verbose=True, use_cache=not args.no_cache)

    if not results:
        print("  ✅ All packages are up to date!")
    else:
        print(f"\n  Found {len(results)} outdated package(s):\n")
        print(f"  {'Package':<30} {'Installed':>12} {'Latest':>12}")
        print(f"  {'-'*30} {'-'*12} {'-'*12}")
        for r in results:
            print(f"  {r['name']:<30} {r['installed']:>12} → {r['latest']:>10}")

    if failed:
        print(
            f"\n  ⚠️  Could not check {len(failed)} package(s) "
            f"(network error, not necessarily up to date): {', '.join(failed)}"
        )


# ── check-deps ──────────────────────────────────────────────────────────────

def cmd_check_deps(args) -> None:
    """Compare installed packages against declared requirements/pyproject deps."""
    venv_path = _resolve_venv(args)
    project_root = Path(args.project) if args.project else Path.cwd()

    declared, sources = find_declared_dependencies(project_root)
    if not declared:
        print(
            f"[error] No dependencies found in requirements.txt or pyproject.toml "
            f"under: {project_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        tree = get_dependency_tree(venv_path)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    drift = compute_dependency_drift(tree, declared)

    _header("Dependency Drift Check")
    print(f"  Declared dependencies: {len(declared)}  (from {', '.join(sources)})")

    orphaned_count = len(drift["orphaned"])
    _header(f"Orphaned — installed but not required by any declared package ({orphaned_count})")
    if not drift["orphaned"]:
        print("  None — every installed package is reachable from a declared dependency.")
    else:
        for name in drift["orphaned"]:
            print(f"  {name}")

    _header(f"Missing — declared but not installed ({len(drift['missing'])})")
    if not drift["missing"]:
        print("  None.")
    else:
        for name in drift["missing"]:
            print(f"  {name}")


# ── scan ────────────────────────────────────────────────────────────────────

def cmd_scan(args) -> None:
    """Scan a directory for all virtual environments."""
    root = Path(args.scan_path)
    if not root.exists():
        print(f"[error] Path does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    print(f"\nScanning for virtual environments in: {root}")
    print("(This may take a moment…)\n")

    ignore_dirs = tuple(load_config().get("ignore_dirs", []))
    summaries = scan_all(root, extra_ignore=ignore_dirs)

    if not summaries:
        print("  No virtual environments found.")
        return

    # ── Duplicates HTML mode ──
    if args.duplicates_html:
        dupes = duplicate_packages(summaries)
        venv_paths = [s["path"] for s in summaries]
        html = to_duplicates_html(
            duplicates=dupes,
            scan_path=str(root),
            total_envs=len(summaries),
            venv_paths=venv_paths,
        )
        out_path = Path(args.duplicates_html)
        out_path.write_text(html, encoding="utf-8")
        print(f"Duplicate Package Dashboard saved to: {out_path}")
        return

    # ── Duplicates JSON/CSV report mode ──
    if args.duplicates_report:
        dupes = duplicate_packages(summaries)
        out_path = Path(args.duplicates_report)
        suffix = out_path.suffix.lower()

        if suffix == ".csv":
            out_path.write_text(to_duplicates_csv(dupes), encoding="utf-8")
        elif suffix in (".json", ""):
            content = to_duplicates_json(dupes, scan_path=str(root), total_envs=len(summaries))
            out_path.write_text(content, encoding="utf-8")
        else:
            print(
                f"[error] Unknown report format '{suffix}'. Use .json or .csv",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Duplicate Package report saved to: {out_path}")
        return

    # ── Duplicates mode ──
    if args.duplicates:
        dupes = duplicate_packages(summaries)
        _header("Duplicate Packages Across Environments")

        if not dupes:
            print("  No duplicate packages found.")
            return

        total_wasted = 0
        dupes_by_size = sorted(
            dupes.items(),
            key=lambda kv: -sum(e["size_bytes"] for e in kv[1]),
        )
        for name, entries in dupes_by_size:
            total_size = sum(e["size_bytes"] for e in entries)
            total_wasted += total_size
            # The "wasted" amount is all copies minus one (keep one canonical)
            wasted = total_size - max(e["size_bytes"] for e in entries)
            print(f"\n  {name}  — installed in {len(entries)} environments")
            print(f"    Combined size : {human_size(total_size)}")
            print(f"    Potential save: {human_size(wasted)}")
            for e in entries:
                print(f"    • {e['venv']}  v{e['version']}  {human_size(e['size_bytes'])}")

        print(f"\n  Total potential savings: {human_size(total_wasted)}")
        return

    # ── Cleanup mode ──
    if args.cleanup:
        candidates = cleanup_candidates(summaries, days_old=args.days_old)
        _header(f"Cleanup Candidates (untouched for ≥{args.days_old} days)")

        if not candidates:
            print(f"  No environments older than {args.days_old} days found.")
            return

        total_reclaimable = sum(c["total_bytes"] for c in candidates)
        for c in candidates:
            print(
                f"\n  {c['path']}\n"
                f"    Size         : {c['total_size_human']}\n"
                f"    Last modified: {c['days_ago']} days ago\n"
                f"    Packages     : {c['package_count']}"
            )
        print(f"\n  Total reclaimable: {human_size(total_reclaimable)}")
        return

    # ── Default scan output ──
    _header(f"Found {len(summaries)} Virtual Environment(s)")
    total_all = sum(s["total_bytes"] for s in summaries)

    for s in summaries:
        pct = (s["total_bytes"] / total_all * 100) if total_all else 0
        status = (
            f"⚠️  last used {s['last_modified_days_ago']}d ago"
            if s["last_modified_days_ago"] > 90
            else ""
        )
        print(
            f"\n  {s['path']}\n"
            f"    Size    : {s['total_size_human']} ({pct:.1f}% of total)\n"
            f"    Packages: {s['package_count']}"
            + (f"\n    {status}" if status else "")
            + (f"\n    [error]: {s['error']}" if s.get("error") else "")
        )

    print(f"\n  Total across all environments: {human_size(total_all)}")


# ── compare ─────────────────────────────────────────────────────────────────

def cmd_compare(args) -> None:
    """Compare the installed packages of two virtual environments."""
    venv_a = Path(args.venv_a)
    venv_b = Path(args.venv_b)
    for label, p in (("A", venv_a), ("B", venv_b)):
        if not p.exists():
            print(f"[error] Venv {label} path does not exist: {p}", file=sys.stderr)
            sys.exit(1)

    try:
        result = compare_venvs(venv_a, venv_b)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(to_json(result))
        return

    _header("Environment Comparison")
    print(f"  A: {result['venv_a']}  ({human_size(result['total_bytes_a'])})")
    print(f"  B: {result['venv_b']}  ({human_size(result['total_bytes_b'])})")

    _header(f"Only in A ({len(result['only_in_a'])})")
    for p in result["only_in_a"]:
        print(f"  {p['name']:<30} v{p['version']:<15} {human_size(p['size_bytes'])}")

    _header(f"Only in B ({len(result['only_in_b'])})")
    for p in result["only_in_b"]:
        print(f"  {p['name']:<30} v{p['version']:<15} {human_size(p['size_bytes'])}")

    mismatches = result["common_version_mismatch"]
    _header(f"Version Mismatches ({len(mismatches)})")
    for p in mismatches:
        print(f"  {p['name']:<30} A: v{p['version_a']:<12} B: v{p['version_b']}")

    print(f"\n  Common packages, same version: {len(result['common_same_version'])}")


# ═══════════════════════════════════════════════════════════════════════════
# Argument parser
# ═══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    config = load_config()

    parser = argparse.ArgumentParser(
        prog="venvdoctor",
        description="Analyse Python virtual environments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  venvdoctor                          Analyse current environment
  venvdoctor --top 5                  Show top 5 packages
  venvdoctor --json                   Output JSON to stdout
  venvdoctor --venv /path/to/venv     Analyse a specific venv
  venvdoctor --report report.csv      Save CSV report
  venvdoctor --html dashboard.html    Save HTML dashboard
  venvdoctor --tree                   Show dependency tree
  venvdoctor --largest-deps           Packages by total dep impact
  venvdoctor --package numpy          Info about a single package
  venvdoctor --outdated               Check for outdated packages
  venvdoctor scan /path/to/projects   Scan directory for all venvs
  venvdoctor scan /path --duplicates  Find duplicated packages
  venvdoctor scan /path --duplicates-html report.html   Save duplicate HTML dashboard
  venvdoctor scan /path --duplicates-report report.json Save duplicate report (.json/.csv)
  venvdoctor scan /path --cleanup     Cleanup recommendations
  venvdoctor compare venvA venvB      Compare packages between two venvs
""",
    )

    # ── Global options ──
    parser.add_argument(
        "--venv",
        metavar="PATH",
        help="Path to the virtual environment to analyse (default: current).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=config.get("top", 10),
        metavar="N",
        help="Number of top packages to show (default: 10, or 'top' in .venvdoctor.toml).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )
    parser.add_argument(
        "--report",
        metavar="FILE",
        help="Save report to FILE (.json / .csv / .html).",
    )
    parser.add_argument(
        "--html",
        metavar="FILE",
        help="Save HTML dashboard to FILE.",
    )
    parser.add_argument(
        "--tree",
        action="store_true",
        help="Show dependency tree.",
    )
    parser.add_argument(
        "--largest-deps",
        dest="largest_deps",
        action="store_true",
        help="Show packages by total dependency size impact.",
    )
    parser.add_argument(
        "--package",
        metavar="NAME",
        help="Show detailed info for a specific package.",
    )
    parser.add_argument(
        "--outdated",
        action="store_true",
        help="Check PyPI for outdated packages.",
    )
    parser.add_argument(
        "--no-cache",
        dest="no_cache",
        action="store_true",
        help="Bypass the local PyPI lookup cache used by --outdated "
        "(~/.venvdoctor/pypi_cache.json).",
    )
    parser.add_argument(
        "--check-deps",
        dest="check_deps",
        action="store_true",
        help="Compare installed packages against requirements.txt/pyproject.toml.",
    )
    parser.add_argument(
        "--project",
        metavar="PATH",
        help="Project directory to read requirements.txt/pyproject.toml from "
        "for --check-deps (default: current directory).",
    )

    # ── scan sub-command ──
    sub = parser.add_subparsers(dest="subcommand")
    scan_parser = sub.add_parser("scan", help="Scan a directory for all virtual environments.")
    scan_parser.add_argument("scan_path", metavar="PATH", help="Directory to scan.")
    scan_parser.add_argument(
        "--duplicates",
        action="store_true",
        help="Find packages installed across multiple environments.",
    )
    scan_parser.add_argument(
        "--duplicates-html",
        dest="duplicates_html",
        metavar="FILE",
        help="Save duplicate packages HTML dashboard to FILE.",
    )
    scan_parser.add_argument(
        "--duplicates-report",
        dest="duplicates_report",
        metavar="FILE",
        help="Save duplicate packages report to FILE (.json / .csv).",
    )
    scan_parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Suggest old or large environments to remove.",
    )
    scan_parser.add_argument(
        "--days-old",
        dest="days_old",
        type=int,
        default=config.get("days_old", 90),
        metavar="N",
        help="Days threshold for cleanup recommendations "
        "(default: 90, or 'days_old' in .venvdoctor.toml).",
    )

    # ── compare sub-command ──
    compare_parser = sub.add_parser(
        "compare", help="Compare installed packages between two virtual environments."
    )
    compare_parser.add_argument("venv_a", metavar="VENV_A", help="First environment path.")
    compare_parser.add_argument("venv_b", metavar="VENV_B", help="Second environment path.")
    compare_parser.add_argument(
        "--json",
        action="store_true",
        help="Output the comparison as JSON.",
    )

    return parser


# ═══════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = build_parser()
    args   = parser.parse_args()

    # ── scan sub-command ──
    if args.subcommand == "scan":
        cmd_scan(args)
        return

    # ── compare sub-command ──
    if args.subcommand == "compare":
        cmd_compare(args)
        return

    # ── Feature flags (non-default modes) ──
    if args.report:
        cmd_report(args)
        return

    if args.html:
        cmd_html(args)
        return

    if args.tree:
        cmd_tree(args)
        return

    if args.largest_deps:
        cmd_largest_deps(args)
        return

    if args.package:
        cmd_package(args)
        return

    if args.outdated:
        cmd_outdated(args)
        return

    if args.check_deps:
        cmd_check_deps(args)
        return

    # ── Default: analyse ──
    cmd_analyse(args)


if __name__ == "__main__":
    main()