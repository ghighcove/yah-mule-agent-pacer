# Yah Mule — Development History

## What This Tool Is

Yah Mule is a live Claude efficiency monitor for Claude Max subscribers. It tracks:
- **Quota utilization** — % of weekly Claude Max allotment used (real capacity gate)
- **Spend efficiency** — value extracted per subscription dollar (efficiency ratio)
- **Spend pattern** — cost vs historical weekly average (habit/budget tracker)

Data source: `ccusage` (npm, authoritative) + `G:/ai/_data/analytics.db` (SQLite history).

**Entry point**: always `yah_mule.py` → delegates to current display module.

---

## Version Timeline

### v0 — "The Idea" (pre-tooling)

Origin: Glenn tracking Claude session costs manually, noticing wide variance in value/cost ratio. The insight: flat-rate subscription means efficiency = output value / opportunity cost, not just dollar spend. A 15x ratio means you're getting 15x your subscription dollar in value. Below 12x is a warning sign.

Photos from this period document the initial conceptual sketches and manual tracking approach. See `assets/dev_history/image (8).png` and `image (7).png` — earliest captures of the concept before code existed.

---

### v1 — `kpi_display.py` (rolling stdout)

**Status**: Deprecated. Still present for reference. Do not run via `watch.ps1`.

**Key features:**
- Plain stdout, no dependencies beyond standard library + ccusage
- Three independent dimensions: quota utilization, spend efficiency, spend pattern
- Two independent weekly caps: ALL-MODELS cap (Billy/Haiku heavy) and SONNET-ONLY cap
  - Both track independently; gates use whichever is more constraining
- `--calibrate N [--sonnet-pct M]` to recalibrate caps against Claude.ai /usage
- Persistent config in `quota_config.json`

**Design philosophy**: "No rich required — plain stdout, runs in any terminal." Maximum portability.

**Why deprecated**: Rolling stdout means old data scrolls off. No persistent visual state. Reactor/smokestack metaphors couldn't be rendered.

Historical captures of v1 in operation: `assets/dev_history/image (6).png`, `image (5).png`.

---

### v2 — `kpi_display_v2.py` + `yah_mule.py` (rich.live full-screen)

**Current version**: 2.2.0

**Key additions over v1:**
- `rich.live` full-screen layout — no scroll, entire terminal height used
- Reactor/smokestack metaphor: visual status indicators (NORMAL, HIGH, HEAVY)
- `watch.ps1` thin launcher delegates to `yah_mule.py --interval N` (manages its own loop)
- `yah_mule.py` as stable entry point — underlying display module can change without users updating their launch commands

**Architecture**:
```
watch.ps1
    └── yah_mule.py        (stable launcher — always use this)
            └── kpi_display_v2.py  (current display implementation)
```

**Watch.ps1 fix (2026-02-24)**: Original watch.ps1 ran a PowerShell while loop calling `kpi_display.py` (v1). Rewritten as thin launcher calling `yah_mule.py --interval 60`. Now v2 manages its own refresh loop.

---

### Cap Fixes (2026-02-24)

`usage_tracker.py` had two uncapped→capped regressions:
- **DB write** (line 131): `week_pct = min(week_cost / WEEKLY_API_BASELINE, 1.0)` — capped at 100% in DB
- **Outbox report** (line 162): `week_pct = min(..., 100)` — same cap in markdown report

Both caps removed. `session_check.py` also had the same cap in its budget display. All three are now uncapped — real values like 361% (a busy 3-day week) display correctly.

The $55/week `WEEKLY_API_BASELINE` is an **API-equivalent cost tracking baseline**, not a real budget. Claude Max is flat-rate; 361% means a highly productive week, not overspend.

---

## Deprecated Assets Convention

Files that are superseded but retained for reference:

| File | Status | Replaced by |
|------|--------|-------------|
| `kpi_display.py` | Deprecated (v1) | `kpi_display_v2.py` via `yah_mule.py` |

**Convention**: Do not delete deprecated files. They document the evolution and serve as fallback reference. Mark them in this file, not in the source code itself.

---

## Key Design Decisions

1. **`yah_mule.py` as stable entry point** — callers always use this; display module is an implementation detail.
2. **`watch.ps1` as thin launcher** — no loop logic in PowerShell; v2 manages its own rich.live refresh.
3. **Uncapped budget display** — real values, even >100%, because the baseline is a productivity yardstick, not a hard limit.
4. **ccusage as authoritative source** — handles deduplication and uses live LiteLLM pricing. SQLite DB is cache/history only.
5. **Two cap model** — ALL-MODELS cap (binding when Billy/Haiku runs heavy) and SONNET-ONLY cap (personal productivity yardstick). Gates use whichever is more constraining.

---

## Running the Monitor

```powershell
# Recommended: run in a dedicated Windows Terminal pane
powershell -ExecutionPolicy Bypass -File G:\ai\yah-mule-agent-pacer\watch.ps1

# Or directly:
python G:\ai\yah-mule-agent-pacer\yah_mule.py --interval 60

# Single-shot (for scripting):
python G:\ai\yah-mule-agent-pacer\yah_mule.py --once

# Recalibrate weekly quota cap:
python G:\ai\yah-mule-agent-pacer\yah_mule.py --calibrate 15 --sonnet-pct 12
```

Screenshot: `docs/screenshot.jpg` (current)
Promo assets: `assets/promo/yah-mule-38.jpg` through `yah-mule-43.jpg`

---

## Asset Convention

When the main screenshot or promo photos are updated, **move the previous version to `assets/dev_history/`** rather than deleting it. Use sequential naming (image 1, 2, 3... where lower numbers are more recent).

```
assets/
  promo/            ← current promo-ready shots
    yah-mule-38.jpg
    ...
  dev_history/      ← superseded versions, reverse-chron (higher number = older)
    image (4).png   ← most recent superseded
    image (5).png
    ...
    image (8).png   ← oldest
docs/
  screenshot.jpg    ← current public-facing screenshot
```

**Retroactive status**: `docs/screenshot.jpg` is the live screenshot. No deprecated screenshots exist in `docs/` yet — convention applies to future updates.
