# YAH!!! Mule Agent Pacer

![YAH!!!](assets/promo/yah-mule-43.jpg)

> *"Know your quota. Work the mules hard. Don't go over."*

A live terminal dashboard for Claude Max subscribers running heavy agentic workloads. Tracks weekly API spend, efficiency ratios, hourly burn patterns, and projected quota utilization — so you can drive the mules hard without blowing the reactor.

---

## Why This Exists

Claude Max is flat-rate — you pay the same whether you run 5 sessions or 50. Every idle cycle and shallow session is money you already paid for and didn't use.

Yah Mule tracks three things: how much quota you've burned this week, how much value you're extracting per dollar, and whether you're pacing the week correctly. The goal: hit 85–90% of quota by reset, with a consistent efficiency ratio, no runaway burns.

---

## Live Dashboard

![Yah Mule v2.7 in action](docs/screenshot.jpg)

Full-screen `rich.live` terminal UI. Clock ticks every 5 seconds; spend and efficiency data refreshes every 5 minutes.

---

## Requirements

- Python 3.8+
- [`rich`](https://github.com/Textualize/rich) — `pip install rich`
- [`ccusage`](https://github.com/ryoppippi/ccusage) CLI — `npm install -g ccusage` (requires Node.js)
- A Claude Max subscription

---

## Quick Start

```bash
# Clone this repo
git clone https://github.com/ghighcove/yah-mule-agent-pacer.git
cd yah-mule-agent-pacer

# Install ccusage (authoritative data source)
npm install -g ccusage

# Launch the live monitor
python yah_mule.py

# Single-shot output and exit
python yah_mule.py --once

# Windows: persistent terminal window
open_monitor.bat
```

Run `--calibrate` once with your actual weekly quota number before the numbers mean anything (see Calibration below).

---

## Calibration — Set These Once

Four things to configure to your actual subscription. Skip this and the numbers will be wrong.

### 1. Weekly quota cap

```bash
python yah_mule.py --calibrate <your_weekly_usd_equiv>
```

Find your weekly cap: **claude.ai → Usage**, read the ccusage-equivalent value for the current week, pass it here. Writes `quota_config.json`. Re-calibrate if your tier changes.

### 2. Billing cycle anchor

In `kpi_display_v2.py`, update the anchor date to match your billing cycle:

```python
anchor = date(2026, 2, 7)  # ← your billing cycle start date
```

### 3. Reset hours

```python
ALL_MODELS_RESET_HOUR = 12   # hour your all-models quota resets (0–23)
SONNET_RESET_HOUR     = 26   # 24 + hour if next-day (e.g. 26 = 2am next day)
```

### 4. Efficiency baseline

```python
RATIO_BASELINE = 15.5   # your "good day" value-per-dollar target
RATIO_FLOOR    = 12.0   # warning threshold
```

Rule of thumb: pull your 30-day average from ccusage, set `RATIO_BASELINE` to ~80% of that, `RATIO_FLOOR` to ~60%. The defaults were calibrated for heavy Sonnet-focused agentic work.

---

## Fine-Tuning

| Constant | Default | What it controls |
|---|---|---|
| `REFRESH_INTERVAL` | 300 | Seconds between data fetches (ccusage + SQLite). Range: 60–600 |
| `QUOTA_SPRINT_GATE` | 0.80 | Threshold to pause new sprint work |
| `QUOTA_ABORT` | 0.90 | Hard stop threshold |
| `QUOTA_SCHED_RESERVE` | 0.05 | Buffer reserved for scheduled/cron jobs |
| `WEEKLY_SPEND_BASELINE` | $55 | Reference for spend% coloring (your historical avg) |
| `PLAN_DAILY_USD` | $100/30 | Daily plan value (used to compute efficiency ratio) |

---

## Reading the Dashboard

### QUOTA UTILIZATION (top left)
Dual spend limits: Claude Max tracks an all-models cap and a Sonnet-specific cap separately. The one closer to its ceiling is your **binding limit**. Green = open, yellow = approaching gate (80%), red = stop sprinting (90%).

### SPEND EFFICIENCY (top right)
The `x` number is your **value-per-dollar ratio** — how much plan-value you're extracting per dollar spent. `25x` means you're generating 25x the baseline daily plan value per dollar. `ON` / `BELOW` / `LOW` shows where you stand vs your target baseline.

This is your quality-of-work signal. Low ratio = shallow sessions, throwaway runs, idle context. High ratio = focused, high-output work.

### SPEND PATTERN
Weekly pacing. `HEAVY` / `HIGH` / `NORMAL` shows spend rate vs historical baseline. `PROJECTED` extrapolates your 3-day average to end-of-week — `FULL` means you'll land around 65–84% of quota (ideal), `GATE` means you'd breach the 80% sprint gate before reset.

### 7-DAY TREND
One bar per day, sized and colored by efficiency ratio. Green = on target, yellow = below baseline, red = well below floor. Lets you spot exploration days vs deep-work days at a glance.

### REACTOR

| Column | What it shows |
|---|---|
| **EFF stack** | Today's efficiency ratio vs baseline. Smoke rings (@@) at top = overflow — well above target |
| **PROJ stack** | Projected end-of-week quota %. The `──` marker = your sprint gate target |
| **Mule** | Color = projected quota risk. Green = GOOD (<65%), yellow = FULL (65–84%), red = GATE (85%+) |
| **Hourglass** | Current hour progress. Top sand (#) depletes, bottom (.) accumulates. Color = this hour's burn vs day average. Label shows `:MM` elapsed and projected `$/h` |

The REACTOR answers in one glance: *"Am I working efficiently, am I pacing the week correctly, and how hot is this hour burning?"*

### TODAY BY HOUR
- **Sparkline** (top row): All 24 hours compressed into a single line using `▁▂▃▄▅▆▇█`. Current hour in `[brackets]`.
- **Stats row**: Peak hour (★), average $/h across active hours, current-hour projected pace.
- **Active hours list**: Current hour shown first. Peak hour marked ★. Pre-dawn hours (0–6h) dimmed.

---

## Sprint Gate Logic

Designed to be used by automation and scheduling patterns to prevent runaway quota burn:

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

## Development History

This tool evolved from manual spreadsheet tracking → rolling stdout → current full-screen `rich.live` dashboard. The full architecture history, version changelog, and design decisions are in [`DEVHISTORY.md`](DEVHISTORY.md).

Visual evolution captured in `assets/dev_history/` — screenshots from each major phase, from initial concept sketches (v0) through v1 rolling stdout to the current reactor display.

---

## Files

| File | Purpose |
|------|---------|
| `yah_mule.py` | Unified launcher — always use this |
| `kpi_display_v2.py` | Live display engine: rich.live full-screen layout, all panels |
| `kpi_display.py` | v1 display + calibration logic (`--calibrate` delegates here) |
| `usage_tracker.py` | Core tracking: daily/weekly aggregation, SQLite persistence |
| `quota_config.json` | Your calibrated quota settings (gitignored, created on first calibration) |
| `open_monitor.bat` | Windows: opens a persistent terminal running the monitor |
| `watch.ps1` | PowerShell launcher |
| `DEVHISTORY.md` | Architectural history, version changelog, design decisions |
| `docs/TECHNICAL.md` | Data flow diagram and architecture reference |
| `docs/screenshot.jpg` | Current live dashboard screenshot |

---

## Credits & Attribution

- **[ccusage](https://github.com/ryoppippi/ccusage)** by ryoppippi — the underlying CLI that tracks Claude Code token usage. Yah Mule reads ccusage output as its authoritative data source.
- Quota monitoring patterns and sprint gate concepts inspired by the Claude Code community on X and open discussions around Claude Max subscription management.
- The KPI design, REACTOR panel, hourglass/sparkline display, sprint gate logic, SQLite persistence layer, terminal UI, and calibration system are original work.

If you recognize something here as yours and want a specific credit added, open an issue.

---

## License

MIT.

---

*YAH!!! — because sometimes the mules need to move.*
