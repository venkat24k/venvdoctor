# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

VenvDoctor is a Python CLI tool that analyzes virtual environments (venv and conda): package disk-usage breakdown, dependency trees, outdated-package detection (via PyPI), multi-environment scanning, duplicate-package detection across environments, requirements/pyproject drift checking, and JSON/CSV/HTML report generation. Pure standard library — no runtime dependencies.

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
venvdoctor --check-deps --project PATH        # requirements.txt/pyproject.toml drift check
venvdoctor --outdated --no-cache              # bypass the ~/.venvdoctor/pypi_cache.json cache

# Or invoke without installing
python -m venvdoctor.cli

# Tests and lint
pytest                      # run tests/ (50 tests as of this writing)
pytest tests/test_tree.py -k largest_deps   # run a single test
ruff check src/ tests/      # lint (see [tool.ruff] in pyproject.toml)
```

CI (`.github/workflows/ci.yml`) runs `ruff check` and `pytest` on push/PR across Ubuntu + Windows, Python 3.10 and 3.12.

## Architecture

Entry point is `venvdoctor = "venvdoctor.cli:main"` (set in `pyproject.toml`). All source lives under `src/venvdoctor/`, discovered by setuptools via `where = ["src"]`.

- **`cli.py`** — argparse-based CLI. Owns the argument parser (`build_parser`), one `cmd_*` function per mode (analyse/report/html/tree/largest-deps/package/outdated/check-deps/scan/compare), and `main()`, which dispatches based on which flags/subcommand were passed. This is the only module that prints user-facing output or touches `sys.exit`; the other modules are pure data/logic and are safe to reuse programmatically. Loads `.venvdoctor.toml` (via `config.py`) at parser-build time to seed `--top`/`--days-old` defaults.

- **`package_analyzer.py`** — core analysis engine, built entirely on `importlib.metadata`. Given a venv path (or `None` for the currently active environment via `sys.prefix`), it locates `site-packages` (handling both the Windows `Lib/site-packages` and Unix `lib/pythonX.Y/site-packages` layouts) and enumerates distributions from there rather than by activating the venv. Exposes `get_package_sizes`, `get_package_detail`, `get_dependency_tree`. Every other module that needs package data goes through this one. For conda environments, each of these three functions merges in `conda.py`'s conda-meta-derived packages (see below) after the dist-info-based scan, skipping any name already covered by dist-info to avoid double-counting.

- **`conda.py`** — reads `<env>/conda-meta/*.json` to cover packages conda installed without pip-style dist-info (compiled libraries like `openssl`, `mkl`, `sqlite` — not Python distributions, so `importlib.metadata` can never see them). `get_conda_packages`/`get_conda_package_detail` compute each package's installed size by summing the actual on-disk size of the files listed in its conda-meta record (not the record's cached `size` field, which is compressed download size and can differ significantly). `normalize_name` (lowercase, `_`→`-`) is the shared name-matching convention other modules (`package_analyzer.py`, `requirements.py`) use to compare names across pip/conda/requirements-file spellings.

- **`tree.py`** — pure presentation/aggregation over the `dict` produced by `get_dependency_tree`: `print_tree` renders the ASCII tree, `largest_deps` does a recursive (cycle-safe, via a `visited` set) sum of a package's own size plus its transitive dependency sizes to rank "impact."

- **`scanner.py`** — multi-environment support. `find_venvs` walks a directory tree looking for venv markers (`pyvenv.cfg`, `conda-meta`), skipping the built-in noise dirs (`node_modules`, `.git`, `__pycache__`, etc.) plus any `extra_ignore` names (from `.venvdoctor.toml`'s `ignore_dirs`), and not recursing into a directory once it's identified as a venv. `scan_all` runs `get_package_sizes` over each found venv **concurrently** (`ThreadPoolExecutor`, 8 workers — scanning is I/O-bound stat-call work) and returns per-venv summaries. `duplicate_packages` indexes those summaries by package name to find packages present in 2+ environments. `compare_venvs(venv_a, venv_b)` diffs two environments' package sets directly (only-in-A, only-in-B, common-same-version, common-version-mismatch), independent of `scan_all`. `cleanup_candidates` flags venvs whose `pyvenv.cfg` mtime is older than a threshold.

- **`outdated.py`** — queries `https://pypi.org/pypi/{name}/json` concurrently (`ThreadPoolExecutor`, 8 workers, 5s timeout per request, 1 retry on transient network/5xx errors — but not on 404, which just means "not on PyPI"). Results are cached per package name at `~/.venvdoctor/pypi_cache.json` (24h TTL, `--no-cache` bypasses it); only the main thread touches the cache dict after the concurrent lookups complete, so no locking is needed. `check_outdated` returns `(results, failed)`: outdated packages plus the names of packages whose lookup failed after retries, so a network blip is never silently reported as "up to date." Version ordering uses `_ver_key`, a regex-based PEP-440-subset parser (epoch, release, pre/post/dev stages) — deliberately not a full PEP 440 implementation (no local-version comparison), but correctly orders pre-releases (`a`/`b`/`rc`), dev releases, and post-releases relative to a final release, which the previous naive dot-split comparator did not.

- **`requirements.py`** — drift check between installed packages and declared dependencies. `find_declared_dependencies` reads `requirements.txt` and/or `pyproject.toml` (`[project.dependencies]` and legacy `[tool.poetry.dependencies]`; TOML parsing needs Python 3.11+'s `tomllib` and degrades to `[]` on older interpreters rather than erroring). `compute_dependency_drift(tree, declared)` walks the full transitive closure of the declared names through a `get_dependency_tree` result (BFS over each package's `deps`) before diffing against what's installed — a flat declared-vs-installed diff would falsely flag every indirect dependency (e.g. numpy pulled in by pandas) as "orphaned."

- **`config.py`** — optional `.venvdoctor.toml` (cwd, then `~/.venvdoctor.toml`; first found wins, no merging) providing defaults for `--top`, `scan --days-old`, and `scan`'s `ignore_dirs`. Same `tomllib`-availability caveat as `requirements.py`: silently returns `{}` on Python < 3.11 or when no file exists, so the feature degrades to "no defaults" rather than failing.

- **`formatters.py`** — output serialization: `human_size` (byte formatting), `to_json`, `to_csv`, and `to_html` (a single self-contained dark-themed HTML dashboard with an inline hand-rolled canvas donut chart — no external JS/CSS dependencies).

- **`formatters_duplicates.py`** — generates the standalone duplicate-package dashboard (`to_duplicates_html`): KPI cards, a log-scaled package×environment heatmap, savings/cumulative/frequency/scatter canvas charts, and a searchable detail table. Also self-contained HTML/CSS/JS with no external dependencies. Also has `to_duplicates_json` / `to_duplicates_csv` for machine-readable duplicate reports (wired to `venvdoctor scan PATH --duplicates-report FILE`). This is the largest and most actively evolving file in the project (see recent commit history around duplicate-dashboard UI).

### Data flow

`cli.py` calls into `package_analyzer.py` (single venv, itself augmented by `conda.py` for conda environments) or `scanner.py` (multi-venv, which calls `package_analyzer.py` per venv concurrently) to gather data as plain dicts/lists, then hands that data to `formatters.py` / `formatters_duplicates.py` / `tree.py` / `requirements.py` to render or cross-reference it as terminal text, JSON, CSV, or HTML. The only on-disk state VenvDoctor itself writes is the PyPI lookup cache (`~/.venvdoctor/pypi_cache.json`) and whatever report files the user asks for — every run otherwise re-reads package metadata from disk (and PyPI for `--outdated`) fresh.

## Project conventions

- No third-party runtime dependencies (`dependencies = []` in `pyproject.toml`); dev-only tools (pytest, ruff) go in `[project.optional-dependencies] dev`, not `dependencies`. Keep it that way unless there's a strong reason to add a runtime dependency.
- Generated report files (`*.json`, `*.csv`, `*.html`) and the `venv/` directory are gitignored — don't assume generated artifacts should be committed, and don't rely on `venv/` contents being tracked.
- HTML dashboards are generated as fully self-contained strings (inline `<style>`/`<script>`, hand-rolled canvas charts) rather than relying on templates or external chart libraries — follow this pattern if extending the dashboards.
- Ruff (`[tool.ruff]` in `pyproject.toml`) ignores E501 (line length) specifically in `formatters.py` and `formatters_duplicates.py`, since those files are mostly embedded HTML/CSS/JS template strings, not line-length-sensitive Python logic. Real Python logic lines should still stay under 100 chars everywhere.
- Tests under `tests/` build real (but minimal) `dist-info`/`conda-meta`/`pyvenv.cfg`/`.venvdoctor.toml` fixtures on `tmp_path` rather than mocking `importlib.metadata` or the filesystem — this exercises the actual discovery code paths. Follow that pattern for new tests against `package_analyzer.py` / `scanner.py` / `conda.py` / `config.py`.
- `pyproject.toml` parsing (`config.py`, `requirements.py`) uses the stdlib `tomllib`, which requires Python 3.11+; both modules import it lazily inside the function that needs it and catch `ModuleNotFoundError` to degrade gracefully (empty result) on 3.9/3.10 rather than raising, since the project's declared minimum is `>=3.9`. Tests covering TOML parsing are marked `@pytest.mark.skipif(sys.version_info < (3, 11), ...)`.
- Package names are compared across sources (pip dist-info, conda-meta, requirements.txt/pyproject.toml) via `conda.py`'s `normalize_name` (lowercase, `_` → `-`) rather than exact string equality, since the same package can be spelled differently across those sources (e.g. `scikit_learn` vs `scikit-learn`).
