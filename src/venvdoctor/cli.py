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
venvdoctor scan PATH --duplicates-html FILE  # save duplicate HTML dashboard
venvdoctor scan PATH --cleanup      # suggest old / large venvs to remove
"""

from __future__ import annotations

import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

from .package_analyzer import get_package_sizes, get_package_detail, get_dependency_tree
from .formatters import human_size, to_json, to_csv, to_html
from .formatters_duplicates import to_duplicates_html
from .tree import print_tree, largest_deps
from .scanner import scan_all, duplicate_packages, cleanup_candidates


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
        print(f"[error] Unknown report format '{suffix}'. Use .json, .csv, or .html", file=sys.stderr)
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

    results = check_outdated(packages, verbose=True)

    if not results:
        print("  ✅ All packages are up to date!")
        return

    print(f"\n  Found {len(results)} outdated package(s):\n")
    print(f"  {'Package':<30} {'Installed':>12} {'Latest':>12}")
    print(f"  {'-'*30} {'-'*12} {'-'*12}")
    for r in results:
        print(f"  {r['name']:<30} {r['installed']:>12} → {r['latest']:>10}")


# ── scan ────────────────────────────────────────────────────────────────────

def cmd_scan(args) -> None:
    """Scan a directory for all virtual environments."""
    root = Path(args.scan_path)
    if not root.exists():
        print(f"[error] Path does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    print(f"\nScanning for virtual environments in: {root}")
    print("(This may take a moment…)\n")

    summaries = scan_all(root)

    if not summaries:
        print("  No virtual environments found.")
        return

    # ── Duplicates HTML mode (must be before terminal duplicates) ──
        # ── Duplicates HTML mode ──
    if args.duplicates_html:
        dupes = duplicate_packages(summaries)
        venv_paths = [s['path'] for s in summaries]
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

    # ── Duplicates mode ──
    if args.duplicates:
        dupes = duplicate_packages(summaries)
        _header("Duplicate Packages Across Environments")

        if not dupes:
            print("  No duplicate packages found.")
            return

        total_wasted = 0
        for name, entries in sorted(dupes.items(), key=lambda kv: -sum(e["size_bytes"] for e in kv[1])):
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
        status = f"⚠️  last used {s['last_modified_days_ago']}d ago" if s["last_modified_days_ago"] > 90 else ""
        print(
            f"\n  {s['path']}\n"
            f"    Size    : {s['total_size_human']} ({pct:.1f}% of total)\n"
            f"    Packages: {s['package_count']}"
            + (f"\n    {status}" if status else "")
            + (f"\n    [error]: {s['error']}" if s.get("error") else "")
        )

    print(f"\n  Total across all environments: {human_size(total_all)}")


# ═══════════════════════════════════════════════════════════════════════════
# Argument parser
# ═══════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
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
  venvdoctor scan /path --duplicates-html report.html  Save duplicate HTML dashboard
  venvdoctor scan /path --cleanup     Cleanup recommendations
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
        default=10,
        metavar="N",
        help="Number of top packages to show (default: 10).",
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
        "--cleanup",
        action="store_true",
        help="Suggest old or large environments to remove.",
    )
    scan_parser.add_argument(
        "--days-old",
        dest="days_old",
        type=int,
        default=90,
        metavar="N",
        help="Days threshold for cleanup recommendations (default: 90).",
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

    # ── Default: analyse ──
    cmd_analyse(args)


if __name__ == "__main__":
    main()