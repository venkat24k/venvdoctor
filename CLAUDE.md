# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

VenvDoctor is a Python CLI tool that analyzes virtual environments: package disk-usage breakdown, dependency trees, outdated-package detection (via PyPI), multi-environment scanning, duplicate-package detection across environments, and JSON/CSV/HTML report generation. Pure standard library — no runtime dependencies.

## Commands

```bash
# Install in editable mode with dev tooling (pytest, ruff)
pip install -e ".[dev]"

# Run the CLI
venvdoctor                          # analyse current venv
venvdoctor --top 5                  # show top 5 packages by size
venvdoctor --json                   # JSON to stdout
venvdoctor --venv PATH              # analyse a venv at PATH instead of the active one
venvdoctor --report out.json|out.csv|out.html
venvdoctor --html dashboard.html
venvdoctor --tree                   # dependency tree
venvdoctor --largest-deps           # packages ranked by own + transitive dep size
venvdoctor --package numpy          # detail for one package
venvdoctor --outdated               # query PyPI JSON API for newer versions
venvdoctor scan PATH                          # find all venvs under PATH
venvdoctor scan PATH --duplicates             # packages installed in 2+ venvs
venvdoctor scan PATH --duplicates-html out.html
venvdoctor scan PATH --duplicates-report out.json|out.csv
venvdoctor scan PATH --cleanup --days-old 60  # stale-venv cleanup candidates
venvdoctor compare VENV_A VENV_B [--json]     # diff packages between two venvs

# Or invoke without installing
python -m venvdoctor.cli

# Tests and lint
pytest                      # run tests/ (28 tests as of this writing)
pytest tests/test_tree.py -k largest_deps   # run a single test
ruff check src/ tests/      # lint (see [tool.ruff] in pyproject.toml)
```

CI (`.github/workflows/ci.yml`) runs `ruff check` and `pytest` on push/PR across Ubuntu + Windows, Python 3.10 and 3.12.

## Architecture

Entry point is `venvdoctor = "venvdoctor.cli:main"` (set in `pyproject.toml`). All source lives under `src/venvdoctor/`, discovered by setuptools via `where = ["src"]`.

- **`cli.py`** — argparse-based CLI. Owns the argument parser (`build_parser`), one `cmd_*` function per mode (analyse/report/html/tree/largest-deps/package/outdated/scan/compare), and `main()`, which dispatches based on which flags/subcommand were passed. This is the only module that prints user-facing output or touches `sys.exit`; the other modules are pure data/logic and are safe to reuse programmatically.

- **`package_analyzer.py`** — core analysis engine, built entirely on `importlib.metadata`. Given a venv path (or `None` for the currently active environment via `sys.prefix`), it locates `site-packages` (handling both the Windows `Lib/site-packages` and Unix `lib/pythonX.Y/site-packages` layouts) and enumerates distributions from there rather than by activating the venv. Exposes `get_package_sizes`, `get_package_detail`, `get_dependency_tree`. Every other module that needs package data goes through this one.

- **`tree.py`** — pure presentation/aggregation over the `dict` produced by `get_dependency_tree`: `print_tree` renders the ASCII tree, `largest_deps` does a recursive (cycle-safe, via a `visited` set) sum of a package's own size plus its transitive dependency sizes to rank "impact."

- **`scanner.py`** — multi-environment support. `find_venvs` walks a directory tree looking for venv markers (`pyvenv.cfg`, `conda-meta`), skipping common noise dirs (`node_modules`, `.git`, `__pycache__`, etc.) and not recursing into a directory once it's identified as a venv. `scan_all` runs `get_package_sizes` (from `package_analyzer`) over each found venv and returns per-venv summaries. `duplicate_packages` indexes those summaries by package name to find packages present in 2+ environments. `compare_venvs(venv_a, venv_b)` diffs two environments' package sets directly (only-in-A, only-in-B, common-same-version, common-version-mismatch), independent of `scan_all`. `cleanup_candidates` flags venvs whose `pyvenv.cfg` mtime is older than a threshold.

- **`outdated.py`** — queries `https://pypi.org/pypi/{name}/json` concurrently (`ThreadPoolExecutor`, 8 workers, 5s timeout per request, 1 retry on transient network/5xx errors — but not on 404, which just means "not on PyPI"). `check_outdated` returns `(results, failed)`: outdated packages plus the names of packages whose lookup failed after retries, so a network blip is never silently reported as "up to date." Version ordering uses `_ver_key`, a regex-based PEP-440-subset parser (epoch, release, pre/post/dev stages) — deliberately not a full PEP 440 implementation (no local-version comparison), but correctly orders pre-releases (`a`/`b`/`rc`), dev releases, and post-releases relative to a final release, which the previous naive dot-split comparator did not.

- **`formatters.py`** — output serialization: `human_size` (byte formatting), `to_json`, `to_csv`, and `to_html` (a single self-contained dark-themed HTML dashboard with an inline hand-rolled canvas donut chart — no external JS/CSS dependencies).

- **`formatters_duplicates.py`** — generates the standalone duplicate-package dashboard (`to_duplicates_html`): KPI cards, a log-scaled package×environment heatmap, savings/cumulative/frequency/scatter canvas charts, and a searchable detail table. Also self-contained HTML/CSS/JS with no external dependencies. Also has `to_duplicates_json` / `to_duplicates_csv` for machine-readable duplicate reports (wired to `venvdoctor scan PATH --duplicates-report FILE`). This is the largest and most actively evolving file in the project (see recent commit history around duplicate-dashboard UI).

### Data flow

`cli.py` calls into `package_analyzer.py` (single venv) or `scanner.py` (multi-venv, which itself calls `package_analyzer.py` per venv) to gather data as plain dicts/lists, then hands that data to `formatters.py` / `formatters_duplicates.py` / `tree.py` to render it as terminal text, JSON, CSV, or HTML. There is no persistent state or database — every run re-reads package metadata from disk (and PyPI for `--outdated`).

## Project conventions

- No third-party runtime dependencies (`dependencies = []` in `pyproject.toml`); dev-only tools (pytest, ruff) go in `[project.optional-dependencies] dev`, not `dependencies`. Keep it that way unless there's a strong reason to add a runtime dependency.
- Generated report files (`*.json`, `*.csv`, `*.html`) and the `venv/` directory are gitignored — don't assume generated artifacts should be committed, and don't rely on `venv/` contents being tracked.
- HTML dashboards are generated as fully self-contained strings (inline `<style>`/`<script>`, hand-rolled canvas charts) rather than relying on templates or external chart libraries — follow this pattern if extending the dashboards.
- Ruff (`[tool.ruff]` in `pyproject.toml`) ignores E501 (line length) specifically in `formatters.py` and `formatters_duplicates.py`, since those files are mostly embedded HTML/CSS/JS template strings, not line-length-sensitive Python logic. Real Python logic lines should still stay under 100 chars everywhere.
- Tests under `tests/` build real (but minimal) `dist-info`/`pyvenv.cfg` fixtures on `tmp_path` rather than mocking `importlib.metadata` — this exercises the actual distribution-discovery code path. Follow that pattern for new tests against `package_analyzer.py` / `scanner.py`.
