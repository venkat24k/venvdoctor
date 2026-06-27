"""
formatters_duplicates.py
------------------------
Generate a professional HTML dashboard for duplicate packages across
multiple virtual environments.

Includes KPI cards, an interactive heat map, savings bar charts,
environment footprint analysis, copy-frequency histogram, and a
detailed duplicate table — all self-contained (no external deps).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from .formatters import human_size


def _short_path(path: str, max_len: int = 28) -> str:
    """Return a shortened display label for a venv path."""
    p = Path(path)
    label = p.name
    if len(label) <= max_len:
        return label
    return label[: max_len - 1] + "…"


def _wasted_bytes(entries: list[dict]) -> int:
    if not entries:
        return 0
    biggest = max(e["size_bytes"] for e in entries)
    return sum(e["size_bytes"] for e in entries) - biggest


def to_duplicates_html(
    duplicates: dict[str, list[dict]],
    scan_path: str,
    generated_at: str = "",
    total_envs: int = 0,
    venv_paths: list[str] | None = None,
) -> str:
    """
    Return a complete HTML page visualising duplicate packages.

    duplicates : { package_name -> [ {venv, version, size_bytes}, ... ] }
    venv_paths : list of all scanned environment paths (for the matrix)
    """
    if not generated_at:
        generated_at = datetime.now().isoformat(timespec="seconds")
    if venv_paths is None:
        venv_paths = []

    sorted_pkgs = sorted(
        duplicates.items(),
        key=lambda kv: -sum(e["size_bytes"] for e in kv[1]),
    )

    total_combined = sum(
        sum(e["size_bytes"] for e in entries) for _, entries in sorted_pkgs
    )
    total_wasted = sum(_wasted_bytes(entries) for _, entries in sorted_pkgs)

    avg_copies = (
        sum(len(entries) for _, entries in sorted_pkgs) / len(sorted_pkgs)
        if sorted_pkgs else 0
    )
    top_waste_pkg = sorted_pkgs[0][0] if sorted_pkgs else "—"
    top_waste_val = _wasted_bytes(sorted_pkgs[0][1]) if sorted_pkgs else 0
    version_mismatch = sum(
        1
        for _, entries in sorted_pkgs
        if len({e.get("version", "?") for e in entries}) > 1
    )

    env_labels = [_short_path(p) for p in venv_paths]
    env_labels_full = list(venv_paths)

    # ── Heat map data (log-scaled 0–1 per cell) ──
    heat_packages: list[str] = []
    heat_matrix: list[list[float]] = []
    heat_sizes: list[list[int]] = []
    heat_versions: list[list[str]] = []
    max_cell_bytes = 1

    for pkg_name, entries in sorted_pkgs[:40]:
        env_map = {e["venv"]: e for e in entries}
        row_vals: list[float] = []
        row_sizes: list[int] = []
        row_vers: list[str] = []
        for path in venv_paths:
            entry = env_map.get(path)
            if entry:
                sz = entry["size_bytes"]
                row_sizes.append(sz)
                row_vers.append(entry.get("version", "?"))
                max_cell_bytes = max(max_cell_bytes, sz)
            else:
                row_sizes.append(0)
                row_vers.append("")
        heat_packages.append(pkg_name)
        heat_sizes.append(row_sizes)
        heat_versions.append(row_vers)

    for row in heat_sizes:
        scaled = []
        for sz in row:
            if sz <= 0:
                scaled.append(0.0)
            else:
                scaled.append(math.log1p(sz) / math.log1p(max_cell_bytes))
        heat_matrix.append(scaled)

    # ── Per-environment duplicate footprint ──
    env_footprint: dict[str, int] = {p: 0 for p in venv_paths}
    for _, entries in sorted_pkgs:
        for e in entries:
            if e["venv"] in env_footprint:
                env_footprint[e["venv"]] += e["size_bytes"]

    env_footprint_data = [
        {"name": _short_path(p), "full": p, "bytes": env_footprint[p]}
        for p in venv_paths
    ]
    env_footprint_data.sort(key=lambda x: x["bytes"], reverse=True)

    # ── Copy frequency (how many packages appear in N envs) ──
    copy_freq: dict[int, int] = {}
    for _, entries in sorted_pkgs:
        n = len(entries)
        copy_freq[n] = copy_freq.get(n, 0) + 1

    copy_freq_data = [
        {"copies": k, "count": v}
        for k, v in sorted(copy_freq.items())
    ]

    # ── Top savings bar chart ──
    bar_data = []
    for pkg_name, entries in sorted_pkgs[:12]:
        wasted = _wasted_bytes(entries)
        bar_data.append({
            "name": pkg_name,
            "wasted": wasted,
            "combined": sum(e["size_bytes"] for e in entries),
            "copies": len(entries),
        })
    max_bar = max((d["wasted"] for d in bar_data), default=1)

    # ── Cumulative waste (for area chart) ──
    cumulative_data = []
    running = 0
    for pkg_name, entries in sorted_pkgs[:20]:
        w = _wasted_bytes(entries)
        running += w
        cumulative_data.append({
            "name": pkg_name,
            "wasted": w,
            "cumulative": running,
        })

    # ── Heat map HTML rows ──
    heat_rows_html = ""
    for i, pkg_name in enumerate(heat_packages):
        cells = ""
        for j, path in enumerate(venv_paths):
            sz = heat_sizes[i][j]
            ver = heat_versions[i][j]
            intensity = heat_matrix[i][j]
            if sz > 0:
                title = f"{pkg_name} @ {_short_path(path, 60)}\\n{human_size(sz)} · v{ver}"
                cells += (
                    f'<td class="heat-cell" data-intensity="{intensity:.4f}" '
                    f'title="{title}" data-label="{pkg_name}" '
                    f'data-env="{env_labels[j]}" data-size="{human_size(sz)}" '
                    f'data-version="{ver}">'
                    f'<span class="heat-label">{human_size(sz)}</span></td>'
                )
            else:
                cells += '<td class="heat-cell heat-empty" data-intensity="0" title="Not installed">—</td>'
        combined = sum(heat_sizes[i])
        wasted = _wasted_bytes(
            [{"size_bytes": s} for s in heat_sizes[i] if s > 0]
        )
        heat_rows_html += (
            f"<tr><td class='heat-pkg' title='{pkg_name}'>{pkg_name}</td>"
            f"{cells}"
            f"<td class='mono heat-total'>{human_size(combined)}</td>"
            f"<td class='mono heat-save'>{human_size(wasted)}</td></tr>"
        )

    # ── Detail table rows ──
    detail_rows = ""
    for idx, (pkg_name, entries) in enumerate(sorted_pkgs):
        combined = sum(e["size_bytes"] for e in entries)
        wasted = _wasted_bytes(entries)
        waste_pct = (wasted / combined * 100) if combined else 0
        versions = {e.get("version", "?") for e in entries}
        version_badge = (
            '<span class="badge badge-warn">version mismatch</span>'
            if len(versions) > 1
            else '<span class="badge badge-ok">same version</span>'
        )
        env_chips = ""
        for e in entries:
            env_chips += (
                f'<div class="env-chip">'
                f'<span class="chip-path" title="{e["venv"]}">{_short_path(e["venv"], 36)}</span>'
                f'<span class="chip-ver">v{e.get("version", "?")}</span>'
                f'<span class="chip-size">{human_size(e["size_bytes"])}</span>'
                f"</div>"
            )
        detail_rows += f"""
        <tr class="detail-row" data-name="{pkg_name.lower()}">
          <td class="pkg-name">{pkg_name}</td>
          <td class="mono center">{len(entries)}</td>
          <td class="mono">{human_size(combined)}</td>
          <td class="mono save-col">{human_size(wasted)}</td>
          <td class="waste-bar-cell">
            <div class="inline-bar-bg">
              <div class="inline-bar-fill" style="width:{min(waste_pct, 100):.1f}%"></div>
            </div>
            <span class="inline-bar-pct">{waste_pct:.0f}%</span>
          </td>
          <td>{version_badge}</td>
          <td class="env-chips-cell">{env_chips}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Duplicate Packages — VenvDoctor</title>
<style>
  :root {{
    --bg:          #090b10;
    --bg-elevated: #0f1219;
    --surface:     #141820;
    --surface-2:   #1a2030;
    --border:      #252b3a;
    --border-light:#2f384d;
    --accent:      #6366f1;
    --accent-soft: rgba(99, 102, 241, 0.15);
    --accent-glow: rgba(99, 102, 241, 0.35);
    --teal:        #2dd4bf;
    --teal-soft:   rgba(45, 212, 191, 0.12);
    --amber:       #fbbf24;
    --rose:        #f43f5e;
    --rose-soft:   rgba(244, 63, 94, 0.12);
    --text:        #e8eaef;
    --text-2:      #a1a8b8;
    --muted:       #6b7289;
    --mono:        'JetBrains Mono', 'Cascadia Code', 'Fira Code', ui-monospace, monospace;
    --sans:        'Segoe UI', system-ui, -apple-system, sans-serif;
    --radius:      12px;
    --radius-sm:   8px;
    --shadow:      0 4px 24px rgba(0,0,0,.35);
    --heat-empty:  #12151c;
    --heat-low:    #1e3a5f;
    --heat-mid:    #6366f1;
    --heat-high:   #f43f5e;
  }}

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    background-image:
      radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,.12), transparent),
      radial-gradient(ellipse 60% 40% at 100% 0%, rgba(45,212,191,.06), transparent);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
  }}

  .page {{
    max-width: 1400px;
    margin: 0 auto;
    padding: 32px 28px 48px;
  }}

  /* ── Header ── */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 24px;
    margin-bottom: 32px;
    padding-bottom: 24px;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }}
  .header-left {{ flex: 1; min-width: 280px; }}
  .eyebrow {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .12em;
    text-transform: uppercase;
    color: var(--teal);
    margin-bottom: 8px;
  }}
  .title {{
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -.02em;
    line-height: 1.2;
  }}
  .title span {{ color: var(--accent); }}
  .subtitle {{
    color: var(--text-2);
    font-size: 13px;
    margin-top: 8px;
    max-width: 640px;
  }}
  .subtitle code {{
    font-family: var(--mono);
    font-size: 12px;
    background: var(--surface);
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid var(--border);
    color: var(--text);
  }}
  .header-meta {{
    text-align: right;
    font-size: 12px;
    color: var(--muted);
    line-height: 1.8;
  }}
  .header-meta strong {{ color: var(--text-2); font-weight: 500; }}

  /* ── KPI grid ── */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 14px;
    margin-bottom: 28px;
  }}
  @media (max-width: 1100px) {{ .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
  @media (max-width: 600px)  {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}

  .kpi {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 16px;
    position: relative;
    overflow: hidden;
    transition: border-color .2s, transform .2s;
  }}
  .kpi:hover {{
    border-color: var(--border-light);
    transform: translateY(-1px);
  }}
  .kpi::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--kpi-accent, var(--accent));
    opacity: .7;
  }}
  .kpi-label {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .1em;
    color: var(--muted);
    margin-bottom: 8px;
  }}
  .kpi-value {{
    font-family: var(--mono);
    font-size: 20px;
    font-weight: 600;
    color: var(--text);
    line-height: 1.2;
  }}
  .kpi-value.accent {{ color: var(--teal); }}
  .kpi-value.warn   {{ color: var(--amber); }}
  .kpi-sub {{
    font-size: 11px;
    color: var(--muted);
    margin-top: 6px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}

  /* ── Layout ── */
  .grid-2 {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  @media (max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}

  .grid-3 {{
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 20px;
    margin-bottom: 20px;
  }}
  @media (max-width: 1100px) {{ .grid-3 {{ grid-template-columns: 1fr; }} }}

  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 22px 24px;
    box-shadow: var(--shadow);
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 20px;
  }}
  .card-title {{
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -.01em;
  }}
  .card-desc {{
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
  }}
  .card-badge {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .08em;
    padding: 4px 10px;
    border-radius: 20px;
    background: var(--accent-soft);
    color: var(--accent);
    white-space: nowrap;
  }}

  /* ── Canvas charts ── */
  .chart-wrap {{
    position: relative;
    width: 100%;
  }}
  canvas.chart {{
    display: block;
    width: 100%;
  }}

  /* ── Heat map ── */
  .heatmap-scroll {{
    overflow-x: auto;
    margin: 0 -4px;
    padding-bottom: 4px;
  }}
  .heatmap-table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 3px;
    min-width: 600px;
  }}
  .heatmap-table th {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--muted);
    padding: 8px 6px;
    text-align: center;
    white-space: nowrap;
  }}
  .heatmap-table th.heat-pkg-col {{
    text-align: left;
    min-width: 140px;
    position: sticky;
    left: 0;
    background: var(--surface);
    z-index: 2;
  }}
  .heat-pkg {{
    font-weight: 600;
    font-size: 12px;
    padding: 6px 10px;
    white-space: nowrap;
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    position: sticky;
    left: 0;
    background: var(--surface);
    z-index: 1;
    border-radius: var(--radius-sm);
  }}
  .heat-cell {{
    text-align: center;
    padding: 0;
    border-radius: var(--radius-sm);
    min-width: 72px;
    height: 36px;
    vertical-align: middle;
    cursor: default;
    transition: transform .15s, box-shadow .15s;
    position: relative;
  }}
  .heat-cell:not(.heat-empty):hover {{
    transform: scale(1.06);
    z-index: 3;
    box-shadow: 0 0 0 2px var(--accent-glow);
  }}
  .heat-empty {{
    background: var(--heat-empty);
    color: var(--muted);
    font-size: 12px;
  }}
  .heat-label {{
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 500;
    color: rgba(255,255,255,.92);
    text-shadow: 0 1px 2px rgba(0,0,0,.5);
    pointer-events: none;
  }}
  .heat-total, .heat-save {{
    font-size: 11px;
    text-align: right;
    padding: 0 8px;
    white-space: nowrap;
  }}
  .heat-save {{ color: var(--teal); }}

  .heat-legend {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 16px;
    flex-wrap: wrap;
  }}
  .heat-legend-label {{
    font-size: 11px;
    color: var(--muted);
  }}
  .heat-gradient {{
    flex: 1;
    min-width: 160px;
    max-width: 280px;
    height: 10px;
    border-radius: 5px;
    background: linear-gradient(90deg, var(--heat-empty), var(--heat-low), var(--heat-mid), var(--heat-high));
    border: 1px solid var(--border);
  }}
  .heat-legend-ends {{
    display: flex;
    justify-content: space-between;
    width: 100%;
    max-width: 280px;
    font-size: 10px;
    color: var(--muted);
    font-family: var(--mono);
  }}

  /* ── Tooltip ── */
  #heat-tooltip {{
    position: fixed;
    pointer-events: none;
    background: var(--bg-elevated);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    font-size: 12px;
    line-height: 1.5;
    box-shadow: var(--shadow);
    z-index: 9999;
    opacity: 0;
    transition: opacity .12s;
    max-width: 260px;
  }}
  #heat-tooltip.visible {{ opacity: 1; }}
  #heat-tooltip .tt-title {{ font-weight: 600; color: var(--text); margin-bottom: 4px; }}
  #heat-tooltip .tt-row {{ color: var(--text-2); }}
  #heat-tooltip .tt-row span {{ color: var(--teal); font-family: var(--mono); }}

  /* ── Detail table ── */
  .table-toolbar {{
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }}
  .search-input {{
    flex: 1;
    min-width: 200px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 9px 14px;
    color: var(--text);
    font-family: var(--sans);
    font-size: 13px;
    outline: none;
    transition: border-color .2s;
  }}
  .search-input:focus {{ border-color: var(--accent); }}
  .search-input::placeholder {{ color: var(--muted); }}
  .table-count {{
    font-size: 12px;
    color: var(--muted);
    align-self: center;
    font-family: var(--mono);
  }}

  .data-table {{
    width: 100%;
    border-collapse: collapse;
  }}
  .data-table th {{
    text-align: left;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  .data-table td {{
    padding: 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .data-table tr:last-child td {{ border-bottom: none; }}
  .data-table tr:hover td {{ background: rgba(255,255,255,.015); }}
  .data-table tr.hidden {{ display: none; }}

  .pkg-name {{ font-weight: 600; font-size: 13px; }}
  .mono {{ font-family: var(--mono); font-size: 12px; }}
  .center {{ text-align: center; }}
  .save-col {{ color: var(--teal); font-weight: 500; }}

  .inline-bar-cell {{
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 110px;
  }}
  .inline-bar-bg {{
    flex: 1;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
  }}
  .inline-bar-fill {{
    height: 100%;
    border-radius: 3px;
    background: linear-gradient(90deg, var(--accent), var(--teal));
  }}
  .inline-bar-pct {{
    font-family: var(--mono);
    font-size: 11px;
    color: var(--muted);
    width: 36px;
    text-align: right;
  }}

  .badge {{
    display: inline-block;
    font-size: 10px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: .04em;
    white-space: nowrap;
  }}
  .badge-ok {{ background: var(--teal-soft); color: var(--teal); }}
  .badge-warn {{ background: var(--rose-soft); color: var(--rose); }}

  .env-chips-cell {{ min-width: 280px; }}
  .env-chip {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 0;
    border-bottom: 1px solid rgba(255,255,255,.04);
    font-size: 12px;
  }}
  .env-chip:last-child {{ border-bottom: none; }}
  .chip-path {{
    flex: 1;
    color: var(--accent);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }}
  .chip-ver {{ color: var(--muted); font-family: var(--mono); font-size: 11px; }}
  .chip-size {{ font-family: var(--mono); font-size: 11px; color: var(--text-2); }}

  .table-scroll {{ overflow-x: auto; }}

  .footer {{
    text-align: center;
    color: var(--muted);
    font-size: 11px;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
  }}
</style>
</head>
<body>
<div class="page">

  <header class="header">
    <div class="header-left">
      <div class="eyebrow">VenvDoctor · Multi-Environment Analysis</div>
      <h1 class="title">Duplicate <span>Package</span> Dashboard</h1>
      <p class="subtitle">
        Storage overlap across <strong>{total_envs}</strong> virtual environments under
        <code>{scan_path}</code>
      </p>
    </div>
    <div class="header-meta">
      <div>Generated <strong>{generated_at}</strong></div>
      <div>Packages in 2+ envs: <strong>{len(duplicates)}</strong></div>
      <div>Version mismatches: <strong>{version_mismatch}</strong></div>
    </div>
  </header>

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi" style="--kpi-accent: var(--accent)">
      <div class="kpi-label">Duplicate Packages</div>
      <div class="kpi-value">{len(duplicates)}</div>
      <div class="kpi-sub">Installed in 2+ environments</div>
    </div>
    <div class="kpi" style="--kpi-accent: var(--teal)">
      <div class="kpi-label">Potential Savings</div>
      <div class="kpi-value accent">{human_size(total_wasted)}</div>
      <div class="kpi-sub">If deduplicated to one copy each</div>
    </div>
    <div class="kpi" style="--kpi-accent: var(--amber)">
      <div class="kpi-label">Combined Size</div>
      <div class="kpi-value warn">{human_size(total_combined)}</div>
      <div class="kpi-sub">Total bytes across all copies</div>
    </div>
    <div class="kpi" style="--kpi-accent: var(--accent)">
      <div class="kpi-label">Environments</div>
      <div class="kpi-value">{total_envs}</div>
      <div class="kpi-sub">Scanned in this report</div>
    </div>
    <div class="kpi" style="--kpi-accent: var(--teal)">
      <div class="kpi-label">Avg Copies / Package</div>
      <div class="kpi-value">{avg_copies:.1f}</div>
      <div class="kpi-sub">Mean install count per duplicate</div>
    </div>
    <div class="kpi" style="--kpi-accent: var(--rose)">
      <div class="kpi-label">Top Waste Package</div>
      <div class="kpi-value" style="font-size:14px">{top_waste_pkg}</div>
      <div class="kpi-sub">{human_size(top_waste_val)} recoverable</div>
    </div>
  </div>

  <!-- Charts row 1 -->
  <div class="grid-2">
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Top Recoverable Storage</div>
          <div class="card-desc">Potential savings if each package existed in only one environment</div>
        </div>
        <span class="card-badge">Bar Chart</span>
      </div>
      <div class="chart-wrap"><canvas id="savingsChart" class="chart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Cumulative Waste Curve</div>
          <div class="card-desc">How quickly savings add up when deduplicating top packages</div>
        </div>
        <span class="card-badge">Area Chart</span>
      </div>
      <div class="chart-wrap"><canvas id="cumulativeChart" class="chart"></canvas></div>
    </div>
  </div>

  <!-- Charts row 2 -->
  <div class="grid-3">
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Duplicate Footprint by Environment</div>
          <div class="card-desc">Total bytes of duplicated packages stored in each venv</div>
        </div>
        <span class="card-badge">Grouped Bar</span>
      </div>
      <div class="chart-wrap"><canvas id="envChart" class="chart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Copy Frequency</div>
          <div class="card-desc">How many packages appear in N environments</div>
        </div>
        <span class="card-badge">Histogram</span>
      </div>
      <div class="chart-wrap"><canvas id="freqChart" class="chart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">Waste vs Combined Size</div>
          <div class="card-desc">Bubble size = number of copies; position = waste efficiency</div>
        </div>
        <span class="card-badge">Scatter</span>
      </div>
      <div class="chart-wrap"><canvas id="scatterChart" class="chart"></canvas></div>
    </div>
  </div>

  <!-- Heat map -->
  <div class="card" style="margin-bottom: 20px">
    <div class="card-header">
      <div>
        <div class="card-title">Package × Environment Heat Map</div>
        <div class="card-desc">
          Color intensity reflects install size (log scale). Hover cells for details.
          Showing top {len(heat_packages)} packages by combined size.
        </div>
      </div>
      <span class="card-badge">Heat Map</span>
    </div>
    <div class="heatmap-scroll">
      <table class="heatmap-table">
        <thead>
          <tr>
            <th class="heat-pkg-col">Package</th>
            {"".join(f'<th title="{p}">{env_labels[i]}</th>' for i, p in enumerate(env_labels_full))}
            <th>Combined</th>
            <th>Savings</th>
          </tr>
        </thead>
        <tbody>{heat_rows_html}</tbody>
      </table>
    </div>
    <div class="heat-legend">
      <span class="heat-legend-label">Size intensity:</span>
      <div>
        <div class="heat-gradient"></div>
        <div class="heat-legend-ends"><span>Empty</span><span>Low</span><span>High</span></div>
      </div>
    </div>
  </div>

  <!-- Detail table -->
  <div class="card">
    <div class="card-header">
      <div>
        <div class="card-title">Detailed Duplicate Breakdown</div>
        <div class="card-desc">All duplicated packages with per-environment install details</div>
      </div>
    </div>
    <div class="table-toolbar">
      <input type="search" class="search-input" id="pkgSearch"
             placeholder="Filter packages…" autocomplete="off"/>
      <span class="table-count" id="tableCount">{len(sorted_pkgs)} packages</span>
    </div>
    <div class="table-scroll">
      <table class="data-table" id="detailTable">
        <thead>
          <tr>
            <th>Package</th>
            <th>Copies</th>
            <th>Combined</th>
            <th>Savings</th>
            <th>Waste %</th>
            <th>Versions</th>
            <th>Environments</th>
          </tr>
        </thead>
        <tbody>{detail_rows}</tbody>
      </table>
    </div>
  </div>

  <footer class="footer">
    VenvDoctor · Duplicate Package Report · {generated_at}
  </footer>
</div>

<div id="heat-tooltip">
  <div class="tt-title"></div>
  <div class="tt-row">Environment: <span class="tt-env"></span></div>
  <div class="tt-row">Size: <span class="tt-size"></span></div>
  <div class="tt-row">Version: <span class="tt-ver"></span></div>
</div>

<script>
(function() {{
  'use strict';

  const PALETTE = [
    '#6366f1','#2dd4bf','#f43f5e','#fbbf24','#818cf8',
    '#34d399','#fb7185','#a78bfa','#38bdf8','#4ade80',
    '#f472b6','#22d3ee'
  ];

  const CSS = getComputedStyle(document.documentElement);
  const COLORS = {{
    bg:       CSS.getPropertyValue('--surface').trim() || '#141820',
    border:   CSS.getPropertyValue('--border').trim() || '#252b3a',
    text:     CSS.getPropertyValue('--text').trim() || '#e8eaef',
    muted:    CSS.getPropertyValue('--muted').trim() || '#6b7289',
    accent:   CSS.getPropertyValue('--accent').trim() || '#6366f1',
    teal:     CSS.getPropertyValue('--teal').trim() || '#2dd4bf',
    rose:     CSS.getPropertyValue('--rose').trim() || '#f43f5e',
    heatEmpty:'#12151c',
    heatLow:  '#1e3a5f',
    heatMid:  '#6366f1',
    heatHigh: '#f43f5e',
  }};

  function humanSize(bytes) {{
    const units = ['B','KB','MB','GB','TB'];
    let val = bytes, idx = 0;
    while (val >= 1024 && idx < units.length - 1) {{ val /= 1024; idx++; }}
    return val.toFixed(val >= 100 ? 0 : val >= 10 ? 1 : 2) + ' ' + units[idx];
  }}

  function setupCanvas(id, height) {{
    const canvas = document.getElementById(id);
    if (!canvas) return null;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    const w = Math.max(rect.width, 280);
    canvas.width = w * dpr;
    canvas.height = height * dpr;
    canvas.style.height = height + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    return {{ canvas, ctx, w, h: height }};
  }}

  function roundRect(ctx, x, y, w, h, r) {{
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }}

  // ── Heat map cell coloring ──
  function heatColor(t) {{
    if (t <= 0) return COLORS.heatEmpty;
    const stops = [
      {{t:0,   c:[18,21,28]}},
      {{t:0.2, c:[30,58,95]}},
      {{t:0.55,c:[99,102,241]}},
      {{t:1,   c:[244,63,94]}},
    ];
    let a = stops[0], b = stops[stops.length-1];
    for (let i = 0; i < stops.length - 1; i++) {{
      if (t >= stops[i].t && t <= stops[i+1].t) {{
        a = stops[i]; b = stops[i+1]; break;
      }}
    }}
    const f = (t - a.t) / (b.t - a.t || 1);
    const r = Math.round(a.c[0] + (b.c[0]-a.c[0])*f);
    const g = Math.round(a.c[1] + (b.c[1]-a.c[1])*f);
    const b_ = Math.round(a.c[2] + (b.c[2]-a.c[2])*f);
    return `rgb(${{r}},${{g}},${{b_}})`;
  }}

  document.querySelectorAll('.heat-cell[data-intensity]').forEach(cell => {{
    const t = parseFloat(cell.dataset.intensity);
    if (t > 0) cell.style.background = heatColor(t);
  }});

  // ── Heat map tooltip ──
  const tooltip = document.getElementById('heat-tooltip');
  document.querySelectorAll('.heat-cell:not(.heat-empty)').forEach(cell => {{
    cell.addEventListener('mouseenter', e => {{
      tooltip.querySelector('.tt-title').textContent = cell.dataset.label || '';
      tooltip.querySelector('.tt-env').textContent = cell.dataset.env || '';
      tooltip.querySelector('.tt-size').textContent = cell.dataset.size || '';
      tooltip.querySelector('.tt-ver').textContent = 'v' + (cell.dataset.version || '?');
      tooltip.classList.add('visible');
    }});
    cell.addEventListener('mousemove', e => {{
      tooltip.style.left = (e.clientX + 14) + 'px';
      tooltip.style.top  = (e.clientY + 14) + 'px';
    }});
    cell.addEventListener('mouseleave', () => tooltip.classList.remove('visible'));
  }});

  // ── Savings bar chart ──
  const barData = {json.dumps(bar_data)};
  (function() {{
    if (!barData.length) return;
    const barH = 28, gap = 10, pad = {{ t: 8, r: 16, b: 8, l: 130 }};
    const h = pad.t + barData.length * (barH + gap) + pad.b;
    const c = setupCanvas('savingsChart', h);
    if (!c) return;
    const {{ ctx, w, h: H }} = c;
    const maxVal = {max_bar} || 1;
    const chartW = w - pad.l - pad.r;

    barData.forEach((item, i) => {{
      const y = pad.t + i * (barH + gap);
      ctx.font = '500 12px ui-monospace, monospace';
      ctx.fillStyle = COLORS.text;
      const label = item.name.length > 18 ? item.name.slice(0,17)+'…' : item.name;
      ctx.fillText(label, 8, y + barH/2 + 4);

      roundRect(ctx, pad.l, y, chartW, barH, 5);
      ctx.fillStyle = COLORS.border;
      ctx.fill();

      const bw = Math.max(2, (item.wasted / maxVal) * chartW);
      const grad = ctx.createLinearGradient(pad.l, 0, pad.l + bw, 0);
      grad.addColorStop(0, COLORS.accent);
      grad.addColorStop(1, COLORS.teal);
      roundRect(ctx, pad.l, y, bw, barH, 5);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.fillStyle = COLORS.muted;
      ctx.font = '500 11px ui-monospace, monospace';
      ctx.fillText(humanSize(item.wasted), pad.l + bw + 8, y + barH/2 + 4);
      ctx.fillStyle = COLORS.muted;
      ctx.font = '10px system-ui, sans-serif';
      ctx.fillText(item.copies + ' copies', w - pad.r - 52, y + barH/2 + 4);
    }});
  }})();

  // ── Cumulative area chart ──
  const cumData = {json.dumps(cumulative_data)};
  (function() {{
    if (!cumData.length) return;
    const H = 220, pad = {{ t: 20, r: 20, b: 44, l: 56 }};
    const c = setupCanvas('cumulativeChart', H);
    if (!c) return;
    const {{ ctx, w }} = c;
    const chartW = w - pad.l - pad.r;
    const chartH = H - pad.t - pad.b;
    const maxCum = cumData[cumData.length-1].cumulative || 1;

    // grid
    ctx.strokeStyle = COLORS.border;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {{
      const gy = pad.t + chartH - (i/4)*chartH;
      ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(w-pad.r, gy); ctx.stroke();
      ctx.fillStyle = COLORS.muted;
      ctx.font = '10px ui-monospace, monospace';
      ctx.fillText(humanSize(maxCum * i/4), 4, gy + 4);
    }}

    // area
    ctx.beginPath();
    cumData.forEach((d, i) => {{
      const x = pad.l + (i / (cumData.length-1 || 1)) * chartW;
      const y = pad.t + chartH - (d.cumulative / maxCum) * chartH;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }});
    ctx.lineTo(pad.l + chartW, pad.t + chartH);
    ctx.lineTo(pad.l, pad.t + chartH);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad.t, 0, pad.t + chartH);
    grad.addColorStop(0, 'rgba(99,102,241,.35)');
    grad.addColorStop(1, 'rgba(99,102,241,.02)');
    ctx.fillStyle = grad;
    ctx.fill();

    // line
    ctx.beginPath();
    cumData.forEach((d, i) => {{
      const x = pad.l + (i / (cumData.length-1 || 1)) * chartW;
      const y = pad.t + chartH - (d.cumulative / maxCum) * chartH;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }});
    ctx.strokeStyle = COLORS.accent;
    ctx.lineWidth = 2;
    ctx.stroke();

    // x labels (sparse)
    ctx.fillStyle = COLORS.muted;
    ctx.font = '9px ui-monospace, monospace';
    const step = Math.max(1, Math.floor(cumData.length / 5));
    cumData.forEach((d, i) => {{
      if (i % step !== 0 && i !== cumData.length-1) return;
      const x = pad.l + (i / (cumData.length-1 || 1)) * chartW;
      const lbl = d.name.length > 10 ? d.name.slice(0,9)+'…' : d.name;
      ctx.save();
      ctx.translate(x, H - 8);
      ctx.rotate(-0.45);
      ctx.fillText(lbl, 0, 0);
      ctx.restore();
    }});
  }})();

  // ── Environment footprint bar chart ──
  const envData = {json.dumps(env_footprint_data)};
  (function() {{
    if (!envData.length) return;
    const H = 200, pad = {{ t: 16, r: 16, b: 52, l: 16 }};
    const c = setupCanvas('envChart', H);
    if (!c) return;
    const {{ ctx, w }} = c;
    const chartW = w - pad.l - pad.r;
    const chartH = H - pad.t - pad.b;
    const maxVal = Math.max(...envData.map(d => d.bytes), 1);
    const barW = Math.min(60, (chartW / envData.length) - 12);
    const totalW = envData.length * (barW + 12);

    envData.forEach((item, i) => {{
      const x = pad.l + (chartW - totalW)/2 + i * (barW + 12);
      const bh = (item.bytes / maxVal) * chartH;
      const y = pad.t + chartH - bh;

      const grad = ctx.createLinearGradient(x, y, x, y + bh);
      grad.addColorStop(0, PALETTE[i % PALETTE.length]);
      grad.addColorStop(1, 'rgba(99,102,241,.4)');
      roundRect(ctx, x, y, barW, bh, 4);
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.fillStyle = COLORS.muted;
      ctx.font = '9px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(humanSize(item.bytes), x + barW/2, y - 4);

      ctx.save();
      ctx.translate(x + barW/2, H - pad.b + 8);
      ctx.rotate(-0.5);
      ctx.fillText(item.name, 0, 0);
      ctx.restore();
    }});
    ctx.textAlign = 'left';
  }})();

  // ── Copy frequency histogram ──
  const freqData = {json.dumps(copy_freq_data)};
  (function() {{
    if (!freqData.length) return;
    const H = 200, pad = {{ t: 16, r: 16, b: 40, l: 40 }};
    const c = setupCanvas('freqChart', H);
    if (!c) return;
    const {{ ctx, w }} = c;
    const chartW = w - pad.l - pad.r;
    const chartH = H - pad.t - pad.b;
    const maxCount = Math.max(...freqData.map(d => d.count), 1);
    const barW = Math.min(48, (chartW / freqData.length) - 16);
    const totalW = freqData.length * (barW + 16);

    freqData.forEach((item, i) => {{
      const x = pad.l + (chartW - totalW)/2 + i * (barW + 16);
      const bh = (item.count / maxCount) * chartH;
      const y = pad.t + chartH - bh;

      roundRect(ctx, x, y, barW, bh, 4);
      ctx.fillStyle = COLORS.teal;
      ctx.globalAlpha = 0.7 + 0.3 * (item.count / maxCount);
      ctx.fill();
      ctx.globalAlpha = 1;

      ctx.fillStyle = COLORS.text;
      ctx.font = '600 13px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.fillText(String(item.count), x + barW/2, y - 6);

      ctx.fillStyle = COLORS.muted;
      ctx.font = '11px system-ui, sans-serif';
      ctx.fillText(item.copies + ' envs', x + barW/2, H - 14);
    }});
    ctx.textAlign = 'left';
  }})();

  // ── Scatter: combined vs wasted, bubble = copies ──
  const scatterData = {json.dumps(bar_data)};
  (function() {{
    if (!scatterData.length) return;
    const H = 200, pad = {{ t: 16, r: 16, b: 36, l: 52 }};
    const c = setupCanvas('scatterChart', H);
    if (!c) return;
    const {{ ctx, w }} = c;
    const chartW = w - pad.l - pad.r;
    const chartH = H - pad.t - pad.b;
    const maxX = Math.max(...scatterData.map(d => d.combined), 1);
    const maxY = Math.max(...scatterData.map(d => d.wasted), 1);
    const maxCopies = Math.max(...scatterData.map(d => d.copies), 2);

    // axes
    ctx.strokeStyle = COLORS.border;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t+chartH); ctx.lineTo(pad.l+chartW, pad.t+chartH);
    ctx.stroke();

    ctx.fillStyle = COLORS.muted;
    ctx.font = '10px system-ui, sans-serif';
    ctx.fillText('Combined →', pad.l + chartW/2 - 30, H - 6);
    ctx.save();
    ctx.translate(12, pad.t + chartH/2);
    ctx.rotate(-Math.PI/2);
    ctx.fillText('Waste →', 0, 0);
    ctx.restore();

    scatterData.forEach((d, i) => {{
      const x = pad.l + (d.combined / maxX) * chartW;
      const y = pad.t + chartH - (d.wasted / maxY) * chartH;
      const r = 6 + (d.copies / maxCopies) * 14;

      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = PALETTE[i % PALETTE.length] + '99';
      ctx.fill();
      ctx.strokeStyle = PALETTE[i % PALETTE.length];
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }});
  }})();

  // ── Table search filter ──
  const search = document.getElementById('pkgSearch');
  const rows = document.querySelectorAll('.detail-row');
  const countEl = document.getElementById('tableCount');
  if (search) {{
    search.addEventListener('input', () => {{
      const q = search.value.trim().toLowerCase();
      let visible = 0;
      rows.forEach(row => {{
        const match = !q || row.dataset.name.includes(q);
        row.classList.toggle('hidden', !match);
        if (match) visible++;
      }});
      countEl.textContent = visible + ' packages';
    }});
  }}

}})();
</script>
</body>
</html>"""