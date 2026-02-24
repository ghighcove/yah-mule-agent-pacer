# Yah Mule — Changelog

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
