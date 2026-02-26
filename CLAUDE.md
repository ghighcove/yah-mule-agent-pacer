# YAH!!! Mule Agent Pacer — Project Instructions

## Purpose

Live terminal KPI dashboard for Claude Max subscribers. Tracks weekly API spend, efficiency ratios, hourly burn patterns, and projected quota utilization. Full-screen rich terminal UI updating every 60 seconds.

## Key Files

- `kpi_display_v2.py` — main display (v2 reactor + smokestacks, use this one)
- `yah_mule.py` — entry point / CLI
- `watch.ps1` — thin launcher (delegates to yah_mule.py --interval N)
- `SPEC.md` — full feature specification
- `DEVHISTORY.md` — architectural history and refactor log

## Architecture

- `rich.Live` display loop: `refresh_per_second=0.2`, `time.sleep(5)` — data fetches every 60s, layout rebuilds every 5s
- Data source: `G:/ai/_data/analytics.db` (efficiency_daily table)
- `watch.ps1` no longer spawns Python subprocess every N seconds — inner loop is self-managed

## Version Bump Policy (MANDATORY — KB-012)

**Every code change that affects behavior must bump `__version__` in the same commit.**
- Patch bump minimum: `2.x.y` → `2.x.(y+1)`
- The version string appears in the display header — it's the only way to know what's running
- Skipped once (f5ce119 shipped as 2.2.0, should have been 2.3.0). Don't repeat.

## Known Fixes

- **CPU churn fix (2026-02-25, f5ce119)**: `refresh_per_second` was 1, `sleep` was 1s → layout rebuilt 60x/min just to tick timestamp. Now 12x/min. Do not revert.
- **Watch.ps1 fix (2026-02-24)**: Eliminated outer PowerShell loop spawning new Python processes. yah_mule.py manages its own refresh loop.
