"""Turns applied_log.csv into a self-contained local HTML dashboard.

No charting library, no CDN -- plain HTML/CSS bars (mark specs: <=24px
thick, rounded data-end, 2px gap between bars, value at the tip) plus a
sortable table. Sequential blue for the category/type/source breakdowns
(these are magnitude-by-label, not multiple identity series); the fixed
status palette for the status breakdown, since those labels carry real
state meaning (good/critical/neutral), not just an arbitrary category.
"""

from __future__ import annotations

import pathlib
import webbrowser
from collections import Counter
from datetime import date
from html import escape

from .tracking import LOG_PATH, STATUSES, SUPPORTED_FILL_SOURCES, LogEntry, load_log

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARD_PATH = REPO_ROOT / "dashboard.html"

# Sequential blue, steps 450/500 from the reference palette -- see
# palette.md. Fixed status palette (never themed).
BAR_HUE_LIGHT = "#2a78d6"
BAR_HUE_DARK = "#3987e5"
STATUS_COLORS = {
    "offer": ("#0ca30c", "#0ca30c"),  # good
    "interview": ("#2a78d6", "#3987e5"),  # informational, not yet resolved
    "rejected": ("#d03b3b", "#e66767"),  # critical
    "filled_pending_review": ("#898781", "#898781"),  # muted -- awaiting your review
    "found": ("#898781", "#898781"),
    "queued": ("#898781", "#898781"),
    "pending": ("#898781", "#898781"),
    "applied": ("#898781", "#898781"),
    "abandoned": ("#898781", "#898781"),  # muted -- a deliberate decision, not a bad outcome
}
STATUS_LABELS = {
    "found": "Found",
    "queued": "Queued",
    "pending": "Pending",
    "filled_pending_review": "Filled, pending review",
    "applied": "Applied",
    "interview": "Interview",
    "rejected": "Rejected",
    "offer": "Offer",
    "abandoned": "Abandoned",
}

# Shown in the dashboard's status legend -- keep in sync with what the code
# actually does for each one (search for the status name if you change
# behavior, don't just edit this text).
STATUS_EXPLANATIONS = {
    "found": "Discovered by search, not yet touched. In the review queue (Greenhouse/Lever/LinkedIn) or Needs-manual-apply (Amazon/Google/TikTok).",
    "queued": "Same as Found in every code path today -- available if you want to hand-mark \"do this one specifically next,\" but nothing sets it automatically.",
    "pending": "You marked this for a manual second look. Same queue behavior as Found -- review will still offer it again.",
    "filled_pending_review": "review just filled this form and is waiting on you to check it and click Submit. Never auto-submitted.",
    "applied": "You (or mail-check, from a confirmation email) confirmed this was actually submitted. No longer in the review queue.",
    "interview": "mail-check (or you) recorded interview/scheduling contact from the company.",
    "rejected": "mail-check (or you) recorded a rejection. Terminal -- mail-check won't downgrade it back down.",
    "offer": "mail-check (or you) recorded an offer. Terminal, same protection as Rejected.",
    "abandoned": "Not being pursued -- either you chose this (dashboard/status/review's 'a'), or search auto-abandoned it (non-US location, or a senior/experienced-required title -- see the Location column and NOTES.md). Removed from the review queue and Needs-manual-apply, and protected the same way Rejected/Offer are -- mail-check and fill won't move it to anything else automatically.",
}


def build_stats(entries: list[LogEntry]) -> dict:
    today = date.today().isoformat()

    status_counts = Counter(e.status for e in entries)
    category_counts = Counter(e.category or "Other" for e in entries)
    type_counts = Counter(e.employment_type or "Full Time" for e in entries)
    source_counts = Counter(e.source for e in entries)
    # Only entries with a known location_type -- pre-location-feature rows
    # and unmatched sources (Amazon/Google/TikTok) don't have one yet, and
    # would otherwise dominate the chart as a meaningless "(none)" bar.
    location_counts = Counter(e.location_type for e in entries if e.location_type)

    applied_today = sum(1 for e in entries if e.applied_at == today)
    found_today = sum(1 for e in entries if e.found_at == today)
    queue_size = sum(
        1 for e in entries if e.status in ("found", "queued") and e.source in SUPPORTED_FILL_SOURCES
    )
    needs_manual = sum(
        1 for e in entries if e.status in ("found", "queued") and e.source not in SUPPORTED_FILL_SOURCES
    )

    applied_total = sum(
        1 for e in entries if e.status in ("applied", "filled_pending_review", "interview", "rejected", "offer")
    )
    resolved = status_counts["interview"] + status_counts["offer"] + status_counts["rejected"]
    response_rate = (resolved / applied_total * 100) if applied_total else 0.0

    found_dates = [e.found_at for e in entries if e.found_at]
    apps_per_week = 0.0
    if found_dates and applied_total:
        earliest = min(found_dates)
        latest = max([e.updated_at for e in entries if e.updated_at] + found_dates)
        span_days = max((date.fromisoformat(latest) - date.fromisoformat(earliest)).days, 1)
        apps_per_week = applied_total / span_days * 7

    return {
        "applied_today": applied_today,
        "found_today": found_today,
        "queue_size": queue_size,
        "needs_manual_apply": needs_manual,
        "response_rate": response_rate,
        "applications_per_week": apps_per_week,
        "total_entries": len(entries),
        "by_category": dict(category_counts.most_common()),
        "by_employment_type": dict(type_counts.most_common()),
        "by_source": dict(source_counts.most_common()),
        "by_location": dict(location_counts.most_common()),
        "by_status": {s: status_counts.get(s, 0) for s in STATUS_LABELS},
    }


def _stat_tile(label: str, value: str) -> str:
    return f"""
    <div class="stat-tile">
      <div class="stat-value">{escape(value)}</div>
      <div class="stat-label">{escape(label)}</div>
    </div>"""


def _bar_row(label: str, count: int, max_count: int, color_light: str, color_dark: str) -> str:
    pct = (count / max_count * 100) if max_count else 0
    return f"""
      <div class="bar-row">
        <div class="bar-label" title="{escape(label)}">{escape(label)}</div>
        <div class="bar-track">
          <div class="bar-fill" style="width: {pct:.1f}%; --bar-light: {color_light}; --bar-dark: {color_dark};"></div>
        </div>
        <div class="bar-value">{count}</div>
      </div>"""


def _bar_chart(title: str, counts: dict[str, int], color_pairs: dict[str, tuple[str, str]] | None = None) -> str:
    if not counts:
        return f'<div class="chart-card"><h3>{escape(title)}</h3><p class="empty">No data yet.</p></div>'
    max_count = max(counts.values())
    rows = []
    for label, count in counts.items():
        if color_pairs and label in color_pairs:
            c_light, c_dark = color_pairs[label]
        else:
            c_light, c_dark = BAR_HUE_LIGHT, BAR_HUE_DARK
        display_label = STATUS_LABELS.get(label, label) if color_pairs else label
        rows.append(_bar_row(display_label, count, max_count, c_light, c_dark))
    return f'<div class="chart-card"><h3>{escape(title)}</h3>{"".join(rows)}</div>'


def _status_cell(entry: LogEntry, interactive: bool) -> str:
    if not interactive:
        return f"<td>{escape(STATUS_LABELS.get(entry.status, entry.status))}</td>"
    options = "".join(
        f'<option value="{escape(s)}"{" selected" if s == entry.status else ""}>'
        f'{escape(STATUS_LABELS.get(s, s))}</option>'
        for s in STATUSES
    )
    return (
        f'<td><select class="status-select" data-url="{escape(entry.url)}" '
        f'onchange="updateStatus(this)">{options}</select></td>'
    )


def _table_rows(entries: list[LogEntry], interactive: bool = False) -> str:
    rows = []
    for e in entries:
        rows.append(f"""
        <tr data-status="{escape(e.status)}">
          <td>{escape(e.company)}</td>
          <td><a href="{escape(e.url)}" target="_blank" rel="noopener">{escape(e.role)}</a></td>
          <td>{escape(e.category)}</td>
          <td>{escape(e.employment_type)}</td>
          <td>{escape(e.source)}</td>
          <td title="{escape(e.location)}">{escape(e.location_type)}</td>
          {_status_cell(e, interactive)}
          <td>{escape(e.found_at)}</td>
          <td>{escape(e.applied_at)}</td>
        </tr>""")
    return "".join(rows)


def render_html(stats: dict, entries: list[LogEntry], interactive: bool = False) -> str:
    tiles = "".join([
        _stat_tile("Applied today", str(stats["applied_today"])),
        _stat_tile("Found today", str(stats["found_today"])),
        _stat_tile("Queue (ready to review)", str(stats["queue_size"])),
        _stat_tile("Needs manual apply", str(stats["needs_manual_apply"])),
        _stat_tile("Response rate", f"{stats['response_rate']:.0f}%"),
        _stat_tile("Applications / week", f"{stats['applications_per_week']:.1f}"),
    ])

    charts = "".join([
        _bar_chart("By category", stats["by_category"]),
        _bar_chart("By type", stats["by_employment_type"]),
        _bar_chart("By source", stats["by_source"]),
        _bar_chart("By location", stats["by_location"]),
        _bar_chart("By status", stats["by_status"], color_pairs=STATUS_COLORS),
    ])

    table_rows = _table_rows(entries, interactive=interactive)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job search dashboard</title>
<style>
  :root {{
    color-scheme: light;
    --surface-1: #fcfcfb;
    --page: #f9f9f7;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --muted: #898781;
    --gridline: #e1e0d9;
    --border: rgba(11,11,11,0.10);
    --bar-track: #e1e0d9;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
      --surface-1: #1a1a19;
      --page: #0d0d0d;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --muted: #898781;
      --gridline: #2c2c2a;
      --border: rgba(255,255,255,0.10);
      --bar-track: #2c2c2a;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --gridline: #2c2c2a;
    --border: rgba(255,255,255,0.10);
    --bar-track: #2c2c2a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 32px 24px 64px;
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); font-size: 13px; margin: 0 0 28px; }}
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }}
  .stat-tile {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px;
  }}
  .stat-value {{ font-size: 26px; font-weight: 600; }}
  .stat-label {{ font-size: 12px; color: var(--text-secondary); margin-top: 4px; }}
  .charts-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
  }}
  .chart-card {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    overflow-x: auto;
  }}
  .chart-card h3 {{ font-size: 13px; font-weight: 600; margin: 0 0 14px; color: var(--text-secondary); }}
  .chart-card .empty {{ color: var(--muted); font-size: 13px; margin: 0; }}
  .bar-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
  .bar-row:last-child {{ margin-bottom: 0; }}
  .bar-label {{ flex: 0 0 150px; font-size: 12px; color: var(--text-secondary); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ flex: 1; height: 20px; background: var(--bar-track); border-radius: 4px; overflow: hidden; }}
  .bar-fill {{
    height: 100%;
    min-width: 2px;
    background: var(--bar-light);
    border-radius: 4px;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .bar-fill {{ background: var(--bar-dark); }}
  }}
  :root[data-theme="dark"] .bar-fill {{ background: var(--bar-dark); }}
  .bar-value {{ flex: 0 0 28px; font-size: 12px; color: var(--text-primary); font-variant-numeric: tabular-nums; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 13px; }}
  th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--gridline); }}
  th {{ color: var(--text-secondary); font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }}
  th:hover {{ color: var(--text-primary); }}
  tr:last-child td {{ border-bottom: none; }}
  a {{ color: inherit; }}
  .table-wrap {{ overflow-x: auto; }}
  .status-select {{
    font: inherit;
    font-size: 13px;
    color: var(--text-primary);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 6px;
  }}
  .status-select.saving {{ opacity: 0.5; }}
  .table-toolbar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-bottom: 10px; font-size: 13px; color: var(--text-secondary); }}
  .table-toolbar select {{
    font: inherit; font-size: 13px; color: var(--text-primary); background: var(--surface-1);
    border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px;
  }}
  .status-legend {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 14px 18px; margin-bottom: 20px; font-size: 13px;
  }}
  .status-legend summary {{ cursor: pointer; font-weight: 600; color: var(--text-secondary); }}
  .status-legend summary:hover {{ color: var(--text-primary); }}
  .status-legend dl {{ margin: 12px 0 0; }}
  .status-legend dt {{ font-weight: 600; margin-top: 10px; }}
  .status-legend dt:first-child {{ margin-top: 0; }}
  .status-legend dd {{ margin: 2px 0 0; color: var(--text-secondary); }}
</style>
</head>
<body>
  <h1>Job search dashboard</h1>
  <p class="subtitle">{stats["total_entries"]} tracked postings &middot; {"live, editable -- pick a status to save it" if interactive else "generated from applied_log.csv &middot; to correct a status, run <code>python -m autofill status --list</code>"}</p>

  <details class="status-legend">
    <summary>What do the statuses mean?</summary>
    <dl>
      {"".join(f"<dt>{escape(STATUS_LABELS.get(s, s))}</dt><dd>{escape(STATUS_EXPLANATIONS.get(s, ''))}</dd>" for s in STATUSES)}
    </dl>
  </details>

  <div class="kpi-row">{tiles}</div>
  <div class="charts-grid">{charts}</div>

  <div class="table-toolbar">
    <label for="status-filter">Filter status:</label>
    <select id="status-filter">
      <option value="">All statuses</option>
      {"".join(f'<option value="{escape(s)}">{escape(STATUS_LABELS.get(s, s))}</option>' for s in STATUSES)}
    </select>
    <label for="sort-order">Sort by found date:</label>
    <select id="sort-order">
      <option value="newest">Newest first</option>
      <option value="oldest">Oldest first</option>
    </select>
    <span id="filter-count"></span>
  </div>

  <div class="table-wrap">
    <table id="log-table">
      <thead>
        <tr>
          <th data-col="0">Company</th>
          <th data-col="1">Role</th>
          <th data-col="2">Category</th>
          <th data-col="3">Type</th>
          <th data-col="4">Source</th>
          <th data-col="5">Location</th>
          <th data-col="6">Status</th>
          <th data-col="7">Found</th>
          <th data-col="8">Applied</th>
        </tr>
      </thead>
      <tbody>{table_rows}
      </tbody>
    </table>
  </div>

<script>
  const logTbody = document.querySelector('#log-table tbody');

  function sortByColumn(col, desc) {{
    const rows = Array.from(logTbody.querySelectorAll('tr'));
    rows.sort((a, b) => {{
      const av = a.children[col].innerText.trim();
      const bv = b.children[col].innerText.trim();
      return desc ? bv.localeCompare(av) : av.localeCompare(bv);
    }});
    rows.forEach(r => logTbody.appendChild(r));
  }}

  document.querySelectorAll('#log-table th').forEach(th => {{
    th.addEventListener('click', () => {{
      const col = parseInt(th.dataset.col, 10);
      const asc = th.dataset.asc !== 'true';
      document.querySelectorAll('#log-table th').forEach(h => delete h.dataset.asc);
      th.dataset.asc = asc;
      sortByColumn(col, !asc);
      if (col === 7) document.getElementById('sort-order').value = asc ? 'oldest' : 'newest';
    }});
  }});

  function applyFoundSort(newestFirst) {{
    sortByColumn(7, newestFirst);
    document.querySelectorAll('#log-table th').forEach(h => delete h.dataset.asc);
    document.querySelector('#log-table th[data-col="7"]').dataset.asc = String(!newestFirst);
  }}
  document.getElementById('sort-order').addEventListener('change', (e) => {{
    applyFoundSort(e.target.value === 'newest');
  }});

  // Default view: newest-found first (Found is column 7).
  applyFoundSort(true);

  function applyStatusFilter() {{
    const wanted = document.getElementById('status-filter').value;
    let shown = 0;
    logTbody.querySelectorAll('tr').forEach(row => {{
      const match = !wanted || row.dataset.status === wanted;
      row.hidden = !match;
      if (match) shown++;
    }});
    document.getElementById('filter-count').textContent =
      wanted ? `(${{shown}} shown)` : '';
  }}
  document.getElementById('status-filter').addEventListener('change', applyStatusFilter);

  {_status_update_script() if interactive else ""}
</script>
</body>
</html>
"""


def _status_update_script() -> str:
    return """
  async function updateStatus(select) {
    const url = select.dataset.url;
    const status = select.value;
    select.classList.add('saving');
    try {
      const resp = await fetch('/update-status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url, status}),
      });
      if (!resp.ok) throw new Error(await resp.text());
      location.reload();  // refresh stat tiles/charts to reflect the change
    } catch (err) {
      alert('Could not save: ' + err.message);
      select.classList.remove('saving');
    }
  }
"""


def generate(path: pathlib.Path | None = None) -> pathlib.Path:
    path = path or DASHBOARD_PATH
    entries = load_log(LOG_PATH)
    stats = build_stats(entries)
    html = render_html(stats, entries)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def generate_and_open(path: pathlib.Path | None = None) -> pathlib.Path:
    path = generate(path)
    webbrowser.open(f"file://{path}")
    return path
