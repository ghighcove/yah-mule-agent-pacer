# Yah Mule — Technical Architecture

**Version**: 2.7.1
**Last updated**: 2026-02-28

---

## Data Flow Diagram

```
 ┌─────────────────────────────────────────────────────────────────┐
 │                        DATA SOURCES                             │
 │                                                                 │
 │  ccusage CLI ──────────────────────────────────────────────┐   │
 │  (daily/hourly token breakdown per model, JSON output)     │   │
 │                                                            │   │
 │  ~/.claude/projects/**/conversations.json ─────────────┐  │   │
 │  (raw session data — hourly scan, today only)          │  │   │
 │                                                        │  │   │
 │  quota_config.json ─────────────────────────────────┐  │  │   │
 │  (calibrated weekly quota, billing anchor, etc.)    │  │  │   │
 └─────────────────────────────────────────────────────┼──┼──┼───┘
                                                       │  │  │
                                               ┌───────▼──▼──▼───────┐
                                               │    FETCH LAYER       │
                                               │  kpi_display_v2.py   │
                                               │                      │
                                               │  fetch_ccusage_json()│
                                               │  fetch_db_history()  │
                                               │  fetch_hourly_today()│
                                               │  load_quota_config() │
                                               │  fetch_all() ←──────── every REFRESH_INTERVAL seconds
                                               └──────────┬───────────┘
                                                          │
                                               ┌──────────▼───────────┐
                                               │    LAYOUT ENGINE      │
                                               │  build_layout(d, ts) │
                                               │                      │
                                               │  build_quota_panel() │
                                               │  build_efficiency_*()│
                                               │  build_reactor()     │
                                               │  build_hourly_*()    │
                                               └──────────┬───────────┘
                                                          │
                                               ┌──────────▼───────────┐
                                               │   TERMINAL DISPLAY   │
                                               │   rich.Live()        │
                                               │                      │
                                               │  refresh: every 5s   │
                                               │  (clock tick only)   │
                                               └──────────────────────┘
```

---

## Two-Loop Architecture

Yah Mule runs two loops with different cadences:

```
 time.sleep(5) ──────────► Display loop (every 5s)
                             └── Updates timestamp only (no data re-fetch)
                             └── refresh_per_second=0.2 (rich.Live visual update)

 REFRESH_INTERVAL ──────► Data fetch loop (default: every 300s)
                             └── Runs ccusage subprocess
                             └── Reads SQLite efficiency_daily table
                             └── Reads ~/.claude/projects/ for hourly scan
                             └── Rebuilds full layout on new data
```

**Why two loops?** Data fetching (ccusage subprocess + SQLite reads) is relatively expensive. The display clock needs to tick every few seconds to show an accurate timestamp, but the underlying KPI data doesn't change second-to-second. Separating them keeps CPU load near-zero between data fetches.

**Ratio**: With defaults (5s display / 300s data), data fetches 1x per 60 display ticks.

---

## Data Sources Detail

| Source | What it provides | Fetch frequency |
|--------|-----------------|-----------------|
| `ccusage daily --json --breakdown` | Daily spend + model breakdown for past 8 days | `REFRESH_INTERVAL` |
| `~/.claude/projects/` directory scan | Today's hourly token distribution (current-session accuracy) | `REFRESH_INTERVAL` (mtime-cached) |
| `quota_config.json` | Weekly quota cap, billing anchor date, Sonnet quota | `REFRESH_INTERVAL` |
| Internal constants | Baseline, floor, sprint gate thresholds | Startup only |

**No external API calls.** All data is local: ccusage reads Claude Code's own session files, and quota_config.json is written by `--calibrate`.

---

## Key Files

| File | Role |
|------|------|
| `yah_mule.py` | Entry point. Delegates to `kpi_display_v2.main()`. Do not run kpi_display_v2.py directly. |
| `kpi_display_v2.py` | Display engine: fetch layer + layout builder + `rich.Live` loop. All logic lives here. |
| `kpi_display.py` | v1 engine + calibration logic. `--calibrate` flag is handled here. Still imported by v2 for calibration. |
| `usage_tracker.py` | Daily/weekly aggregation, SQLite persistence (writes `usage_data.db`). |
| `quota_config.json` | Calibrated settings (gitignored). Created by `--calibrate`, read at each data fetch. |
| `open_monitor.bat` | Windows: opens a detached terminal window running `python yah_mule.py`. |

---

## Panels and What They Read

| Panel | Data source |
|-------|-------------|
| QUOTA UTILIZATION | `ccusage` weekly sum → compare to `quota_config.json` cap |
| SPEND EFFICIENCY | `ccusage` cost + `PLAN_DAILY_USD` → value-per-dollar ratio |
| SPEND PATTERN | `ccusage` 3-day rolling average → vs `WEEKLY_SPEND_BASELINE` |
| 7-DAY TREND | SQLite `efficiency_daily` table (14-day window) |
| REACTOR (EFF/PROJ stacks) | `ccusage` + quota config → today's ratio + projected week% |
| REACTOR (Hourglass) | `~/.claude/projects/` hourly scan → current-hour burn |
| TODAY BY HOUR | `~/.claude/projects/` hourly scan → 24-hour distribution |

---

## Tuning REFRESH_INTERVAL

`REFRESH_INTERVAL` is defined near the top of `kpi_display_v2.py`:

```python
REFRESH_INTERVAL = 300   # default: 5 minutes
```

This controls how often ccusage and SQLite are queried. The display clock ticks every 5s regardless.

**Trade-offs:**

| Setting | Effect |
|---------|--------|
| `60` (1 min) | Very responsive. Each data fetch takes ~200ms (ccusage subprocess). At 60s you'll notice the brief flicker. Good for active sprints where you want fresh numbers. |
| `300` (5 min, default) | Balanced. Fresh enough to track session progress. CPU impact negligible. |
| `600` (10 min) | Minimal overhead. Good for long-running background sessions or low-power machines. |

You can also override at runtime without editing the file:

```bash
python yah_mule.py --interval 60    # 1-minute refresh for this session
python yah_mule.py --interval 600   # 10-minute refresh
```

The `--interval` flag overrides `REFRESH_INTERVAL` for that run only.

---

## Version Policy

Every behavioral code change requires a `__version__` bump in `kpi_display_v2.py`. The version appears in the display header — it's the only way to confirm what's running at a glance.

Format: `MAJOR.MINOR.PATCH` — patch bump for small fixes/additions, minor bump for new panels or layout changes.

---

## Architecture History

See `DEVHISTORY.md` for the full refactor log, including:
- Why v2 replaced v1 (rolling stdout → full-screen rich.Live)
- CPU churn fix (2026-02-25): `refresh_per_second` 1 → 0.2, sleep 1s → 5s
- Watch.ps1 outer loop elimination (2026-02-24)
- Anthropic billing anchor update (2026-02-26): unified 8pm PT reset
