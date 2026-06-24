"""
formatters_duplicates.py
------------------------
Generate a professional HTML dashboard for duplicate packages across
multiple virtual environments.

Includes summary cards, a waste‑distribution donut, a savings bar chart,
an environment‑package matrix, and a detailed duplicate table.
"""

from __future__ import annotations

import json
from datetime import datetime
from .formatters import human_size


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

    # Sort packages by combined size descending
    sorted_pkgs = sorted(
        duplicates.items(),
        key=lambda kv: -sum(e["size_bytes"] for e in kv[1])
    )

    # ── Stats ──
    total_combined = sum(sum(e["size_bytes"] for e in entries) for _, entries in sorted_pkgs)
    total_wasted = 0
    for _, entries in sorted_pkgs:
        biggest = max(e["size_bytes"] for e in entries)
        total_wasted += sum(e["size_bytes"] for e in entries) - biggest

    # ── Build matrix table ──
    # header: Package | env1 | env2 | ... | total size
    # rows: package name, then per‑env size or "‑"
    matrix_header = "<th>Package</th>"
    for path in venv_paths:
        # shorten path for display (show only last two parts)
        short = Path(path).name
        matrix_header += f"<th class='matrix-env' title='{path}'>{short}</th>"
    matrix_header += "<th>Total Size</th>"

    matrix_rows = ""
    for pkg_name, entries in sorted_pkgs:
        # Build a dict: env_path -> entry
        env_map = {e["venv"]: e for e in entries}
        row = f"<td class='pkg-name'>{pkg_name}</td>"
        for path in venv_paths:
            entry = env_map.get(path)
            if entry:
                size_str = human_size(entry["size_bytes"])
                row += f"<td class='mono matrix-size'>{size_str}</td>"
            else:
                row += "<td class='matrix-missing'>—</td>"
        combined = sum(e["size_bytes"] for e in entries)
        row += f"<td class='mono'>{human_size(combined)}</td>"
        matrix_rows += f"<tr>{row}</tr>"

    # ── Build detailed table ──
    detail_rows = ""
    for pkg_name, entries in sorted_pkgs:
        combined = sum(e["size_bytes"] for e in entries)
        biggest = max(e["size_bytes"] for e in entries)
        wasted = combined - biggest
        env_list = ""
        for e in entries:
            env_list += (
                f"<div class='env-entry'>"
                f"<span class='env-name'>{e['venv']}</span>"
                f"<span class='env-version'>{e['version']}</span>"
                f"<span class='env-size'>{human_size(e['size_bytes'])}</span>"
                f"</div>"
            )
        detail_rows += f"""
        <tr>
            <td class="pkg-name">{pkg_name}</td>
            <td class="mono">{len(entries)}</td>
            <td class="mono">{human_size(combined)}</td>
            <td class="mono">{human_size(wasted)}</td>
            <td>{env_list}</td>
        </tr>"""

    # ── Chart data (JSON for JS) ──
    # Donut: labels = package names, values = wasted per package (top 8, rest other)
    donut_data = []
    other_waste = 0
    for pkg_name, entries in sorted_pkgs[:8]:
        biggest = max(e["size_bytes"] for e in entries)
        wasted = sum(e["size_bytes"] for e in entries) - biggest
        donut_data.append({"name": pkg_name, "wasted": wasted})
    if len(sorted_pkgs) > 8:
        for pkg_name, entries in sorted_pkgs[8:]:
            biggest = max(e["size_bytes"] for e in entries)
            wasted = sum(e["size_bytes"] for e in entries) - biggest
            other_waste += wasted
        donut_data.append({"name": "Other", "wasted": other_waste})

    donut_labels = [d["name"] for d in donut_data]
    donut_values = [d["wasted"] for d in donut_data]

    # Bar chart: top 10 savings
    bar_data = []
    for pkg_name, entries in sorted_pkgs[:10]:
        biggest = max(e["size_bytes"] for e in entries)
        wasted = sum(e["size_bytes"] for e in entries) - biggest
        bar_data.append({"name": pkg_name, "wasted": wasted})
    max_bar = max((d["wasted"] for d in bar_data), default=1)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Duplicate Packages Report — {scan_path}</title>
<style>
  :root {{
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2a2d3a;
    --accent:   #7c6af7;
    --accent2:  #40e0b0;
    --text:     #e2e4ef;
    --muted:    #6b6f8a;
    --mono:     'JetBrains Mono', 'Fira Code', monospace;
    --sans:     'Inter', system-ui, sans-serif;
    --radius:   10px;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    line-height: 1.6;
    padding: 32px 24px;
    max-width: 1200px;
    margin: 0 auto;
  }}

  .header {{
    margin-bottom: 32px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 20px;
  }}
  .logo {{
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -1px;
  }}
  .logo span {{ color: var(--accent); }}
  .meta {{
    color: var(--muted);
    font-size: 12px;
    margin-top: 4px;
  }}

  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }}
  .stat-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
  }}
  .stat-label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .stat-value {{
    font-size: 22px;
    font-weight: 700;
    font-family: var(--mono);
    color: var(--accent);
    word-break: break-word;
  }}

  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-bottom: 24px;
  }}
  .card h2 {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 20px;
  }}

  .chart-row {{
    display: flex;
    gap: 32px;
    align-items: flex-start;
    flex-wrap: wrap;
  }}
  .chart-box {{
    flex: 1;
    min-width: 280px;
  }}
  canvas {{
    width: 100%;
    max-width: 350px;
    height: auto;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
  }}
  th {{
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
  }}
  td {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  tr:last-child td {{ border-bottom: none; }}
  .pkg-name {{ font-weight: 600; }}
  .mono {{ font-family: var(--mono); font-size: 13px; }}

  .env-entry {{
    display: flex;
    gap: 12px;
    align-items: center;
    margin-bottom: 4px;
  }}
  .env-name {{
    color: var(--accent);
    font-weight: 500;
    min-width: 160px;
    font-size: 12px;
  }}
  .env-version {{
    color: var(--muted);
    font-size: 12px;
    min-width: 80px;
  }}
  .env-size {{
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text);
  }}

  .matrix-env {{
    font-size: 12px;
    font-weight: 600;
    color: var(--accent);
    white-space: nowrap;
  }}
  .matrix-size {{ text-align: center; }}
  .matrix-missing {{ color: var(--muted); text-align: center; }}

  .footer {{
    color: var(--muted);
    font-size: 11px;
    text-align: center;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
  }}
</style>
</head>
<body>

<header class="header">
  <div class="logo">Venv<span>Doctor</span></div>
  <div class="meta">
    Scan path: {scan_path} &nbsp;·&nbsp;
    Total environments scanned: {total_envs} &nbsp;·&nbsp;
    Generated {generated_at}
  </div>
</header>

<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-label">Duplicate Packages</div>
    <div class="stat-value">{len(duplicates)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Combined Size</div>
    <div class="stat-value">{human_size(total_combined)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Potential Savings</div>
    <div class="stat-value">{human_size(total_wasted)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Environments Scanned</div>
    <div class="stat-value">{total_envs}</div>
  </div>
</div>

<!-- Charts row -->
<div class="chart-row">
  <div class="chart-box card">
    <h2>Waste by Package</h2>
    <canvas id="donutCanvas"></canvas>
  </div>
  <div class="chart-box card">
    <h2>Top Savings</h2>
    <canvas id="barCanvas"></canvas>
  </div>
</div>

<!-- Environment‑Package Matrix -->
<div class="card">
  <h2>Package Presence Matrix</h2>
  <div style="overflow-x:auto;">
    <table>
      <thead><tr>{matrix_header}</tr></thead>
      <tbody>{matrix_rows}</tbody>
    </table>
  </div>
</div>

<!-- Detailed duplicate table -->
<div class="card">
  <h2>Detailed Duplicate Information</h2>
  <table>
    <thead>
      <tr>
        <th>Package</th>
        <th>Copies</th>
        <th>Combined Size</th>
        <th>Potential Save</th>
        <th>Environments</th>
      </tr>
    </thead>
    <tbody>{detail_rows}</tbody>
  </table>
</div>

<footer class="footer">
  VenvDoctor &nbsp;·&nbsp; Duplicate report generated {generated_at}
</footer>

<script>
// ── Common helpers ──
const PALETTE = ["#7c6af7","#40e0b0","#f76c6c","#f7c26c","#6cb4f7","#c26cf7",
                 "#f76ca8","#6cf799","#f7a06c","#6ce6f7"];

function humanSize(bytes) {{
  const units = ['B','KB','MB','GB','TB'];
  let val = bytes;
  let idx = 0;
  while (val >= 1024 && idx < units.length-1) {{ val /= 1024; idx++; }}
  return val.toFixed(1) + ' ' + units[idx];
}}

// ── Donut chart ──
(function() {{
  const labels = {json.dumps(donut_labels)};
  const values = {json.dumps(donut_values)};
  const total = values.reduce((a,b)=>a+b,0);
  if (total === 0) return;

  const canvas = document.getElementById('donutCanvas');
  const ctx = canvas.getContext('2d');
  const DPR = window.devicePixelRatio || 1;
  const SIZE = 250;
  canvas.width = SIZE * DPR;
  canvas.height = SIZE * DPR;
  canvas.style.width = SIZE + 'px';
  canvas.style.height = SIZE + 'px';
  ctx.scale(DPR, DPR);

  const cx = SIZE/2, cy = SIZE/2, r = SIZE/2 - 15;
  let start = -Math.PI/2;
  values.forEach((val,i) => {{
    const slice = (val/total)*2*Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start+slice);
    ctx.closePath();
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.fill();
    start += slice;
  }});

  // center hole
  ctx.beginPath();
  ctx.arc(cx, cy, r*0.55, 0, 2*Math.PI);
  ctx.fillStyle = getComputedStyle(document.documentElement)
                    .getPropertyValue("--surface").trim() || "#1a1d27";
  ctx.fill();

  // Legend inside card (manual)
  const legendDiv = document.createElement('div');
  legendDiv.style.marginTop = '16px';
  values.forEach((val,i) => {{
    const pct = ((val/total)*100).toFixed(1);
    const item = document.createElement('div');
    item.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px;';
    item.innerHTML = `<div style="width:10px;height:10px;border-radius:50%;background:${{PALETTE[i%PALETTE.length]}}"></div>
                      <span>${{labels[i]}} — ${{pct}}%</span>`;
    legendDiv.appendChild(item);
  }});
  canvas.parentNode.appendChild(legendDiv);
}})();

// ── Bar chart ──
(function() {{
  const data = {json.dumps(bar_data)};
  if (data.length === 0) return;
  const maxVal = {max_bar};

  const canvas = document.getElementById('barCanvas');
  const ctx = canvas.getContext('2d');
  const DPR = window.devicePixelRatio || 1;
  const W = 400, H = data.length * 36 + 20;
  canvas.width = W * DPR;
  canvas.height = H * DPR;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.scale(DPR, DPR);

  const barLeft = 140, barRight = W - 60, barTop = 10, barH = 24, gap = 12;
  ctx.font = '12px "JetBrains Mono", monospace';
  ctx.fillStyle = '#e2e4ef';

  data.forEach((item, i) => {{
    const y = barTop + i * (barH + gap);
    // label
    ctx.fillText(item.name, 10, y + barH/2 + 4);
    // bar background
    const barWidth = (item.wasted / maxVal) * (barRight - barLeft);
    ctx.fillStyle = '#2a2d3a';
    ctx.fillRect(barLeft, y, barRight - barLeft, barH);
    // filled bar
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.fillRect(barLeft, y, barWidth, barH);
    // value text
    ctx.fillStyle = '#e2e4ef';
    ctx.fillText(humanSize(item.wasted), barLeft + barWidth + 6, y + barH/2 + 4);
  }});
}})();
</script>

</body>
</html>"""


# Quick fix – need Path imported for shortening env names
from pathlib import Path