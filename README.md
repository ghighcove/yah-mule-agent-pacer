# YAH!!! Mule Agent Pacer

![YAH!!!](assets/promo/yah-mule-43.jpg)

> *"Know your quota. Work the mules hard. Don't go over."*

A lightweight Claude Max usage monitor and KPI dashboard. Tracks your weekly API spend against your subscription tier, shows real-time utilization, and tells you when to ease off the whip.

---

## What It Does

- **Live quota tracking** — reads `ccusage` output, computes weekly cost against a calibrated weekly budget
- **KPI display** — terminal dashboard with burn rate, projected weekly total, % of quota used, and daily averages
- **Calibration** — set your actual subscription limit once; the pacer gates itself to that number
- **Sprint gate** — configurable thresholds (warn at 80%, stop at 90%) so you don't blow your quota mid-session

Built for [Claude Max](https://claude.ai) subscribers who run heavy agentic workloads and want visibility before hitting the wall.

---

## Requirements

- Python 3.8+
- [`ccusage`](https://github.com/ryoppippi/ccusage) CLI installed and on PATH
- Claude Max subscription

---

## Quick Start

```bash
# Install ccusage (requires Node.js)
npm install -g ccusage

# Clone this repo
git clone https://github.com/ghighcove/yah-mule-agent-pacer.git
cd yah-mule-agent-pacer

# Display current KPIs
python kpi_display.py

# Calibrate to your actual subscription (run once)
# N = your weekly quota in USD-equivalent (check Claude.ai /usage page)
python kpi_display.py --calibrate 1133

# Watch mode (auto-refresh every 30s)
python kpi_display.py --watch

# Windows: open in a persistent terminal window
open_monitor.bat
```

---

## Calibration

The pacer needs to know your weekly budget. Claude Max tiers vary; the default is a placeholder.

1. Go to **claude.ai → Usage** and read your current week's spend
2. Estimate your weekly subscription value (e.g., $20/month ≈ ~$5/week, or use the USD-equivalent from ccusage)
3. Run: `python kpi_display.py --calibrate <your_weekly_budget>`

This writes `quota_config.json` locally. Re-calibrate whenever your usage patterns shift significantly.

---

## Files

| File | Purpose |
|------|---------|
| `kpi_display.py` | Main dashboard — reads ccusage, computes KPIs, displays terminal output |
| `usage_tracker.py` | Core tracking logic — daily/weekly aggregation, SQLite persistence |
| `open_monitor.bat` | Windows: opens a persistent terminal running the monitor |
| `watch.ps1` | PowerShell watch mode for Windows users |
| `SPEC.md` | Design spec and metric definitions |
| `assets/promo/` | Promotional images for dashboards and integrations |

---

## Dashboard Integration

The `assets/promo/` directory contains images suitable for embedding in dashboards, README headers, or sidebar widgets in tools that support custom branding.

| File | Description |
|------|-------------|
| `yah-mule-38.jpg` | Clean hero shot — wide horizontal, no text (good for headers) |
| `yah-mule-39.jpg` | Clean hero shot — portrait, no text (good for sidebars) |
| `yah-mule-40.jpg` | YAH!!! — storm/lightning variant |
| `yah-mule-41.jpg` | YAH!!! — golden hour, text top-right |
| `yah-mule-42.jpg` | YAH!!! — fire glow treatment |
| `yah-mule-43.jpg` | YAH!!! — orange glow, portrait (README default) |

---

## The Sprint Gate Logic

Used by the `/idletime` automation pattern to prevent runaway quota burn:

```python
if quota_pct > 90:
    # STOP. Do not proceed.
    print(f"Quota at {quota_pct:.0f}%. Aborting.")
    sys.exit(1)
elif quota_pct > 80:
    # WARN. Ask before proceeding.
    print(f"Quota at {quota_pct:.0f}%. Proceed? (yes to continue)")
```

---

## License

MIT. Originally spun out from a personal Claude Code automation stack.

---

*YAH!!! — because sometimes the mules need to move.*
