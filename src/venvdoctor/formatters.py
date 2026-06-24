"""
formatters.py
-------------
Output helpers for VenvDoctor.

Provides:
  - human_size(bytes)              -> "3.13 GB"
  - to_json(data)                  -> JSON string
  - to_csv(packages, total_bytes)  -> CSV string
  - to_html(report_data)           -> full HTML page string
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Human-readable sizes
# ---------------------------------------------------------------------------

_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def human_size(num_bytes: int | float) -> str:
    """
    Convert a byte count to a human-readable string.

    Examples
    --------
    >>> human_size(1024)
    '1.00 KB'
    >>> human_size(3_299_541_606)
    '3.07 GB'
    """
    value = float(num_bytes)
    for unit in _UNITS:
        if abs(value) < 1024.0 or unit == _UNITS[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} {_UNITS[-1]}"


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def to_json(data: Any, indent: int = 2) -> str:
    """Serialize *data* to a pretty-printed JSON string."""
    return json.dumps(data, indent=indent, default=str)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def to_csv(packages: list[dict], total_bytes: int) -> str:
    """
    Return a CSV string with one row per package.

    Columns: name, version, size_bytes, size_human, percentage
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "version", "size_bytes", "size_human", "percentage"])

    for pkg in sorted(packages, key=lambda p: p["size_bytes"], reverse=True):
        pct = (pkg["size_bytes"] / total_bytes * 100) if total_bytes else 0.0
        writer.writerow([
            pkg["name"],
            pkg.get("version", "unknown"),
            pkg["size_bytes"],
            human_size(pkg["size_bytes"]),
            f"{pct:.2f}",
        ])

    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML Dashboard (redesigned – clean, professional, no health section)
# ---------------------------------------------------------------------------

def to_html(report: dict) -> str:
    """
    Generate a self-contained, professional HTML dashboard from *report*.

    Expected keys in *report*
    -------------------------
    env_path          str
    python_version    str
    python_executable str
    total_bytes       int
    packages          list[dict]   (name, version, size_bytes)
    generated_at      str          (ISO timestamp, optional)
    """
    packages = sorted(
        report.get("packages", []),
        key=lambda p: p["size_bytes"],
        reverse=True,
    )
    total_bytes = report.get("total_bytes", 0)
    generated_at = report.get("generated_at", datetime.now().isoformat(timespec="seconds"))

    # Build package rows
    rows_html = ""
    for i, pkg in enumerate(packages):
        pct = (pkg["size_bytes"] / total_bytes * 100) if total_bytes else 0.0
        bar_color = _bar_color(pct)
        rows_html += f"""
        <tr class="{'alt' if i % 2 else ''}">
          <td class="pkg-name">{pkg['name']}</td>
          <td class="mono">{pkg.get('version', '—')}</td>
          <td class="mono right">{human_size(pkg['size_bytes'])}</td>
          <td class="pct-cell">
            <div class="bar-bg">
              <div class="bar-fill" style="width:{min(pct,100):.1f}%;background:{bar_color}"></div>
            </div>
            <span class="pct-label">{pct:.1f}%</span>
          </td>
        </tr>"""

    # Top 5 donut chart data
    top5 = packages[:5]
    pie_labels = [p["name"] for p in top5]
    pie_sizes  = [p["size_bytes"] for p in top5]
    other      = total_bytes - sum(pie_sizes)
    if other > 0:
        pie_labels.append("Other")
        pie_sizes.append(other)

    pie_labels_js = json.dumps(pie_labels)
    pie_sizes_js  = json.dumps(pie_sizes)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VenvDoctor Report — {report.get('env_path','')}</title>
<style>
  :root {{
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2a2d3a;
    --accent:   #7c6af7;
    --accent2:  #40e0b0;
    --danger:   #f76c6c;
    --warn:     #f7c26c;
    --ok:       #6cf799;
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
    max-width: 1000px;
    margin: 0 auto;
  }}
  a {{ color: var(--accent); text-decoration: none; }}

  /* ── Header ── */
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

  /* ── Stat cards grid ── */
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
  .stat-value.small {{ font-size: 16px; }}

  /* ── Cards ── */
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
    color: var(--text);
    letter-spacing: .02em;
  }}

  /* ── Donut + Legend row ── */
  .chart-row {{
    display: flex;
    gap: 32px;
    align-items: center;
    flex-wrap: wrap;
  }}
  .chart-canvas-wrapper {{
    flex-shrink: 0;
    width: 220px;
    height: 220px;
  }}
  canvas {{
    width: 220px;
    height: 220px;
  }}
  .legend {{
    flex: 1;
    min-width: 200px;
  }}
  .legend-item {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
    font-size: 13px;
  }}
  .legend-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
  }}

  /* ── Table ── */
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
  }}
  tr.alt td {{
    background: rgba(255,255,255,.02);
  }}
  tr:last-child td {{
    border-bottom: none;
  }}
  .pkg-name {{
    font-weight: 600;
  }}
  .mono {{
    font-family: var(--mono);
    font-size: 13px;
  }}
  .right {{
    text-align: right;
  }}

  /* ── Usage bar ── */
  .pct-cell {{
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 160px;
  }}
  .bar-bg {{
    flex: 1;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    border-radius: 3px;
    transition: width .3s;
  }}
  .pct-label {{
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
    width: 46px;
    text-align: right;
  }}

  /* ── Footer ── */
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
    {report.get('env_path','')} &nbsp;·&nbsp;
    Python {report.get('python_version','')} &nbsp;·&nbsp;
    Generated {generated_at}
  </div>
</header>

<!-- ── Stat cards ── -->
<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-label">Total Size</div>
    <div class="stat-value">{human_size(total_bytes)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Packages</div>
    <div class="stat-value">{len(packages)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Largest Package</div>
    <div class="stat-value small">{packages[0]['name'] if packages else '—'}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Python</div>
    <div class="stat-value small">{report.get('python_version','')}</div>
  </div>
</div>

<!-- ── Disk Usage Donut ── -->
<section class="card">
  <h2>Disk Usage Distribution</h2>
  <div class="chart-row">
    <div class="chart-canvas-wrapper">
      <canvas id="pieChart"></canvas>
    </div>
    <div class="legend" id="pieLegend"></div>
  </div>
</section>

<!-- ── Package Table ── -->
<section class="card">
  <h2>All Packages</h2>
  <table>
    <thead>
      <tr>
        <th>Package</th>
        <th>Version</th>
        <th class="right">Size</th>
        <th>Usage</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</section>

<footer class="footer">
  VenvDoctor &nbsp;·&nbsp; Generated {generated_at}
</footer>

<script>
(function() {{
  const labels  = {pie_labels_js};
  const sizes   = {pie_sizes_js};
  const PALETTE = [
    "#7c6af7","#40e0b0","#f76c6c","#f7c26c","#6cb4f7","#c26cf7",
    "#f76ca8","#6cf799","#f7a06c","#6ce6f7"
  ];
  const total = sizes.reduce((a,b)=>a+b,0);

  // ── Canvas donut ──
  const canvas = document.getElementById("pieChart");
  const ctx    = canvas.getContext("2d");
  const DPR    = window.devicePixelRatio || 1;
  const SIZE   = 220;
  canvas.width  = SIZE * DPR;
  canvas.height = SIZE * DPR;
  canvas.style.width  = SIZE + "px";
  canvas.style.height = SIZE + "px";
  ctx.scale(DPR, DPR);

  const cx = SIZE / 2, cy = SIZE / 2, r = SIZE / 2 - 8;
  let start = -Math.PI / 2;

  sizes.forEach((val, i) => {{
    const slice = (val / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + slice);
    ctx.closePath();
    ctx.fillStyle = PALETTE[i % PALETTE.length];
    ctx.fill();
    start += slice;
  }});

  // inner hole (donut)
  ctx.beginPath();
  ctx.arc(cx, cy, r * 0.55, 0, 2 * Math.PI);
  ctx.fillStyle = getComputedStyle(document.documentElement)
                    .getPropertyValue("--surface").trim() || "#1a1d27";
  ctx.fill();

  // ── Legend ──
  const legend = document.getElementById("pieLegend");
  sizes.forEach((val, i) => {{
    const pct = ((val / total) * 100).toFixed(1);
    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `
      <div class="legend-dot" style="background:${{PALETTE[i % PALETTE.length]}}"></div>
      <span><strong>${{labels[i]}}</strong> — ${{pct}}%</span>`;
    legend.appendChild(item);
  }});
}})();
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Internal helpers (unchanged)
# ---------------------------------------------------------------------------

def _bar_color(pct: float) -> str:
    if pct >= 30:
        return "#f76c6c"
    if pct >= 10:
        return "#f7c26c"
    return "#40e0b0"


def _grade_color(score: int) -> str:
    if score >= 80:
        return "#6cf799"
    if score >= 50:
        return "#f7c26c"
    return "#f76c6c"