# Yah Mule — Standalone Client + Expanded Measurements Spec
**Created**: 2026-02-23
**Status**: Spec only — implementation in a separate session (TD-38/TD-39)

---

## What "Standalone" Means

Current architecture: `watch.ps1` (loop) → `kpi_display.py` (stdout) → terminal window

Standalone = **a single Python process** that owns its own display loop, no PowerShell wrapper needed:
- Uses `rich.live` for a persistent full-terminal UI that updates in place
- Launched with a single command: `python yah_mule.py`
- No shell wrapper, no Clear-Host hacks, no scrolling output
- Full terminal occupancy — every line of the terminal used

This is the natural next step after TD-36 (colorama) and before or alongside the web UI.

---

## Expanded Measurements

### What's Available Now
`kpi_display.py` already computes:
- API-equivalent cost (all-models + sonnet-only)
- Efficiency ratio (today + 7-day rolling)
- Spend vs baseline
- 7-day trend (cost per day)
- Hourly breakdown (cost per hour today)
- Quota utilization (% of weekly cap)
- Sprint room ($$ before gate)
- Reset countdown (hours to each cap reset)

### What's Missing (high value, low effort)

**Token totals by model** — *the key addition*
```
  TOKEN TOTALS  (week to date)
  Sonnet   input: 12.4M   output: 1.8M   cache_r: 8.2M   cache_w: 0.9M
  Haiku    input:  2.1M   output: 0.4M   cache_r: 1.2M   cache_w: 0.1M
  TOTAL    input: 14.5M   output: 2.2M   cache_r: 9.4M   cache_w: 1.0M
```
Source: ccusage JSON `modelBreakdowns[].tokens` fields — already being parsed for cost, just need to surface token counts too.

**Session count today**
```
  SESSIONS TODAY   8 sessions  |  avg 15.2 min  |  longest 47 min
```
Source: count distinct conversation IDs in JSONL files for today's date.

**Cache hit rate**
```
  CACHE EFFICIENCY   cache_read / (cache_read + input) = 62%  (higher = better)
```
Source: already have token counts, just compute the ratio.

**Cost per session (rolling)**
```
  COST/SESSION  today: $1.84  |  7-day avg: $2.11  |  trend: ↓
```
Source: today_cost / session_count

**Rolling 30-day view** (currently only 7 days)
```
  30-DAY TREND
  Week of Feb  7:  $117.82  [████████░░░░░░░░]  18%
  Week of Feb 14:  $145.50  [██████████░░░░░░]  22%
  Week of Feb 21:  $117.82  [████████░░░░░░░░]  18%  <-- current
```
Source: analytics.db `efficiency_daily` — already stored

**Rate limit proximity** (future — needs ccusage to expose this)
- If ccusage exposes remaining rate limit tokens, show as a 4th dimension
- Not available today — placeholder for future

---

## Full-Screen Terminal Layout (rich.live)

Uses `rich` library — `pip install rich` (likely already installed via other tools).

```
┌─────────────────────────── YAH MULE ──────────────────────────────────┐
│  Claude Efficiency Monitor                         2026-02-23  14:32:01│
├─────────────────┬──────────────────────┬──────────────────────────────┤
│ QUOTA           │ EFFICIENCY           │ SPEND PATTERN                │
│                 │                      │                              │
│ ALL  18% ██░░░  │ TODAY  22.4x  GREEN  │ WEEK  $117 / $55 avg  HIGH  │
│ SON  14% █░░░░  │ 7-DAY  19.1x  GREEN  │ PROJ  $145 → 22% cap        │
│                 │ BASE   15.5x         │ DAY 3/7  $7.83 today        │
│ SPRINT ROOM     │ FLOOR  12.0x         │                              │
│ $404 left       │ RATIO = API/plan/day │                              │
├─────────────────┴──────────────────────┴──────────────────────────────┤
│ TOKEN TOTALS (week)                                                    │
│ Sonnet   input 12.4M  output 1.8M  cache_r 8.2M  cache_w 0.9M        │
│ Haiku    input  2.1M  output 0.4M  cache_r 1.2M  cache_w 0.1M        │
│ Cache hit rate: 62%  |  Sessions today: 8  |  Cost/session: $1.84     │
├────────────────────────────────────────────────────────────────────────┤
│ 7-DAY TREND                                  ratio                    │
│ Feb 17  [████████████░░░░░░░░]  22.4x                                 │
│ Feb 18  [████████░░░░░░░░░░░░]  14.1x                                 │
│ Feb 19  [██████████████░░░░░░]  19.8x                                 │
│ Feb 20  [░░░░░░░░░░░░░░░░░░░░]   0.0x                                 │
│ Feb 21  [████████████████░░░░]  24.2x                                 │
│ Feb 22  [██████████░░░░░░░░░░]  15.9x                                 │
│ Feb 23  [████████████░░░░░░░░]  18.3x  <-- today                      │
├────────────────────────────────────────────────────────────────────────┤
│ TODAY BY HOUR                                                          │
│  09 [████░░░░░░░░░░░░░░]  $0.82      15 [░░░░░░░░░░░░░░░░░░]  $0.00  │
│  10 [██████████░░░░░░░░]  $2.14      16 [░░░░░░░░░░░░░░░░░░]  $0.00  │
│  11 [████████░░░░░░░░░░]  $1.63  <-- now                              │
├────────────────────────────────────────────────────────────────────────┤
│  Resets: all-models Mar 1 12pm  |  sonnet Mar 2 2am  |  14h dead zone │
│  Refreshing in 58s  |  Ctrl+C to exit  |  r = refresh now             │
└────────────────────────────────────────────────────────────────────────┘
```

### rich.live Implementation Pattern

```python
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.console import Console
import time

console = Console()

def build_layout(data):
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="kpis",   size=8),
        Layout(name="tokens", size=4),
        Layout(name="trend",  size=10),
        Layout(name="hourly", size=6),
        Layout(name="footer", size=2),
    )
    layout["kpis"].split_row(
        Layout(name="quota"),
        Layout(name="efficiency"),
        Layout(name="spend"),
    )
    # populate each panel...
    return layout

with Live(build_layout(data), refresh_per_second=1, screen=True) as live:
    while True:
        time.sleep(60)
        data = fetch_all_kpi_data()
        live.update(build_layout(data))
```

`screen=True` clears the terminal and owns it completely — no scrollback, full occupancy.

---

## File Structure

```
yah-mule-agent-pacer/
├── kpi_display.py          # existing CLI (kept, still works)
├── watch.ps1               # existing PS wrapper (kept, still works)
├── kpi_data.py             # NEW: pure-data functions, no print statements
│                           #   imported by: kpi_display.py, yah_mule.py, web_monitor_streamlit.py
├── yah_mule.py             # NEW: standalone rich.live full-screen client
├── web_monitor_streamlit.py # NEW (TD-37 build session): Streamlit web UI
├── web_server.py           # NEW (TD-37 HTML+JS option if chosen): Flask backend
├── templates/
│   └── index.html          # NEW (TD-37 HTML+JS option): frontend
├── assets/
│   └── promo/              # mule photos for web UI branding
├── tasks/
│   ├── web_ui_spec.md      # this spec's companion
│   └── standalone_spec.md  # this file
└── open_monitor.bat        # existing launcher (update to point at yah_mule.py)
```

---

## Build Order (for implementation session)

1. **Extract `kpi_data.py`** — move all data-fetching and computation out of `kpi_display.py` into a pure function `compute_kpis()` that returns a dict. No print statements. This unlocks everything else.
2. **Add token totals** to `compute_kpis()` — pull `modelBreakdowns[].tokens` from ccusage JSON
3. **Add session count** — count distinct conversation IDs in today's JSONL files
4. **Build `yah_mule.py`** — `rich.live` full-screen layout consuming `compute_kpis()`
5. **Update `kpi_display.py`** to import from `kpi_data.py` (thin wrapper, preserves existing CLI)
6. **Update `open_monitor.bat`** to launch `yah_mule.py` by default, with a flag to fall back to the PS1 version

---

## Scope Boundary

**In spec**: token totals, session count, cache hit rate, cost/session, 30-day view, rich.live layout
**Out of spec / future**: rate limit API (not available yet), WebSocket push, mobile layout, multi-machine

---

*Spec complete. Ready to build in a dedicated session — estimate 90 min total (kpi_data.py refactor + yah_mule.py).*
