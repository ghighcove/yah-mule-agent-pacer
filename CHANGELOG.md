# Yah Mule — Changelog

## v2.2.0 — 2026-02-23
- **ASCII hourglass**: 4th column in REACTOR — top half (#) empties, bottom half (.) fills as current hour progresses; colored by burn rate vs day avg; label shows `:MM $X.X/h`
- **24-hour sparkline**: replaces nothing, adds a single-line `▁▂▃▄▅▆▇█` view of all hours at the top of TODAY BY HOUR; current hour bracketed in yellow `[X]`
- **Stats row**: peak hour (★), avg $/h, current-hour projected pace — all in one line below sparkline
- **Current hour always first**: active hours list now shows current hour at top (always visible regardless of terminal height), then other active hours ascending
- **Peak hour marker**: `*` next to the highest-cost hour in the active hours list
- **Pre-dawn dimming**: hours 0-6 shown `dim` to reduce visual noise
- **Tighter layout sizes**: top_row 11→9, pattern 7→5, trend 11→9 — saves 6 rows, giving hourly ~6 more rows on any terminal
- **Hourglass in REACTOR**: placed as 4th column alongside mule (no extra height, pure width)

## v2.1.0 — 2026-02-23
- **REACTOR panel**: two ASCII smokestacks (efficiency ratio + projected quota)
- **ASCII mule**: shown in REACTOR panel, colored by projected quota risk (green/yellow/red)
- **Right stack**: now shows projected end-of-week quota (run-rate), not current snapshot
- **Stack labels**: `EFF {x}x` and `PROJ {%}%` for clarity
- **Hourly bars**: heat-map colored by `_stack_color(cost / avg_hour)` — consistent with reactor
- **Unified launcher**: `yah_mule.py` — always use this, regardless of version
- **open_monitor.bat**: updated to launch `yah_mule.py` directly
- Version shown in header bar

## v2.0.0 — 2026-02-22
- Full rewrite using `rich.live` with `screen=True` (full terminal takeover, no scroll)
- 5-panel layout: QUOTA UTILIZATION, SPEND EFFICIENCY, SPEND PATTERN, 7-DAY TREND, TODAY BY HOUR
- Self-contained display loop — no `watch.ps1` wrapper needed
- `--once`, `--interval`, `--calibrate` flags
- Dual quota tracking: all-models + sonnet-only, binding limit detection
- Dead zone / reset countdown display

## v1.0.0 — 2026-02-21
- Initial release: `kpi_display.py` + `watch.ps1` loop
- Rolling stdout with colorama color coding
- Quota, efficiency, spend pattern, 7-day trend, hourly breakdown panels
