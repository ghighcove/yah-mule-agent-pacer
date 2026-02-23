"""
kpi_display.py — Tier 1 live KPI display for Claude efficiency monitor.
Pulls today's data live from ccusage JSON, historical from analytics.db.
No rich required — plain stdout, runs in any terminal.

Three independent dimensions:
  1. QUOTA UTILIZATION  — % of Claude Max weekly allotment used (real capacity)
  2. SPEND EFFICIENCY   — value extracted per subscription dollar (productivity)
  3. SPEND PATTERN      — cost vs historical weekly average (habit tracker)

Two independent weekly caps, both tracked:
  - ALL-MODELS cap:  binding when Haiku (Billy) runs heavy. Resets Sat 12pm PT.
  - SONNET-ONLY cap: primary personal yardstick. Resets Sun 2am PT (+14h).
  Both caps can block independently. Gates use whichever is more constraining.

Recalibrate both caps:
    python kpi_display.py --calibrate 15 --sonnet-pct 12
    (N = % shown in Claude.ai /usage for the respective meter)

Recalibrate all-models only (sonnet cap preserved):
    python kpi_display.py --calibrate 15
"""

import glob
import json
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH     = Path("G:/ai/_data/analytics.db")
CLAUDE_DIR  = Path.home() / ".claude" / "projects"
CONFIG_PATH = Path(__file__).parent / "quota_config.json"

# --- Spend efficiency constants ---
PLAN_DAILY_USD  = 100.0 / 30.0   # $3.33/day pro-rata
RATIO_BASELINE  = 15.5
RATIO_FLOOR     = 12.0

# --- Spend pattern constants ---
WEEKLY_SPEND_BASELINE = 55.0

# --- Quota constants ---
WEEKLY_QUOTA_DEFAULT        = 607.0    # All-models cap (calibrated 2026-02-22)
WEEKLY_SONNET_QUOTA_DEFAULT = 789.0    # Sonnet-only cap (calibrated 2026-02-22)
QUOTA_SPRINT_GATE           = 0.80     # Warn idletime above 80% of binding cap
QUOTA_ABORT                 = 0.90     # Abort idletime above 90% of binding cap
QUOTA_SCHED_RESERVE         = 0.05     # 5% always reserved for crons

# Reset schedule (relative to next_reset midnight, local time)
# All-models: Saturday 12pm PT  →  +12h from midnight
# Sonnet:     Sunday   2am PT   →  +26h from midnight  (14h dead zone)
ALL_MODELS_RESET_HOUR = 12      # noon on reset day
SONNET_RESET_HOUR     = 26      # 2am next day (26 = 24+2)
DEAD_ZONE_HOURS       = SONNET_RESET_HOUR - ALL_MODELS_RESET_HOUR  # 14h

RATES = {
    "claude-sonnet-4-6":            {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5":             {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-opus-4-6":              {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-5":            {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5-20251001":    {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-sonnet-4-5-20250929":   {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
}
DEFAULT_RATE = {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}


# ── Config ────────────────────────────────────────────────────────────────────

def load_quota_config():
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            quota        = cfg.get("weekly_quota_usd_equiv",        WEEKLY_QUOTA_DEFAULT)
            sonnet_quota = cfg.get("weekly_sonnet_quota_usd_equiv", WEEKLY_SONNET_QUOTA_DEFAULT)
            return quota, sonnet_quota, cfg
        except Exception:
            pass
    return WEEKLY_QUOTA_DEFAULT, WEEKLY_SONNET_QUOTA_DEFAULT, {}


def save_quota_config(quota, sonnet_quota, week_cost, claude_pct, sonnet_week_cost=None, sonnet_pct=None):
    cfg = {
        "weekly_quota_usd_equiv":        round(quota, 2),
        "weekly_sonnet_quota_usd_equiv": round(sonnet_quota, 2),
        "calibrated_date":               date.today().isoformat(),
        "calibration_cost_usd":          round(week_cost, 2),
        "calibration_pct":               claude_pct,
        "note": "Recalibrate: python kpi_display.py --calibrate N --sonnet-pct M",
    }
    if sonnet_week_cost is not None:
        cfg["sonnet_calibration_cost_usd"] = round(sonnet_week_cost, 2)
    if sonnet_pct is not None:
        cfg["sonnet_calibration_pct"] = sonnet_pct
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_week_start():
    """Week resets every 7 days from Feb 7 billing anchor."""
    today = date.today()
    billing_anchor = date(2026, 2, 7)
    days_since_anchor = (today - billing_anchor).days
    week_num = days_since_anchor // 7
    return billing_anchor + timedelta(weeks=week_num)


def fetch_ccusage_json(since_days=8):
    """Call ccusage daily --json --breakdown and return parsed data keyed by date."""
    since = (date.today() - timedelta(days=since_days)).strftime("%Y%m%d")
    try:
        result = subprocess.run(
            f"ccusage daily --json --breakdown --since {since}",
            capture_output=True, text=True, timeout=30, shell=True
        )
        data = json.loads(result.stdout)
        return {row["date"]: row for row in data.get("daily", [])}
    except Exception:
        return {}


def model_cost_for_day(day_data: dict, model_prefix: str) -> float:
    """Sum cost for models matching a prefix from modelBreakdowns."""
    if not day_data:
        return 0.0
    total = 0.0
    for breakdown in day_data.get("modelBreakdowns", []):
        if breakdown.get("modelName", "").startswith(model_prefix):
            total += breakdown.get("cost", 0.0)
    return total


def fetch_db_history():
    if not DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        cutoff = (date.today() - timedelta(days=14)).strftime("%Y-%m-%d")
        c.execute(
            "SELECT date, api_cost_usd, efficiency_ratio FROM efficiency_daily WHERE date >= ? ORDER BY date",
            (cutoff,)
        )
        rows = {r[0]: {"cost": r[1], "ratio": r[2]} for r in c.fetchall()}
        conn.close()
        return rows
    except Exception:
        return {}


def bar(value, max_val, width=20, fill="#", empty="-"):
    if max_val <= 0:
        return empty * width
    filled = int(round(min(value / max_val, 1.0) * width))
    return fill * filled + empty * (width - filled)


def quota_status(pct):
    if pct < QUOTA_SPRINT_GATE * 100:
        return "OPEN  "
    elif pct < QUOTA_ABORT * 100:
        return "GATE  "
    else:
        return "PROTECT"


def efficiency_status(ratio):
    if ratio >= RATIO_BASELINE:
        return "ON    "
    elif ratio >= RATIO_FLOOR:
        return "BELOW "
    else:
        return "LOW   "


def spend_status(pct):
    if pct < 75:
        return "NORMAL"
    elif pct < 130:
        return "HIGH  "
    else:
        return "HEAVY "


def trend_status(projected_quota_pct):
    if projected_quota_pct < 30:
        return "LIGHT "
    elif projected_quota_pct < 65:
        return "GOOD  "
    elif projected_quota_pct < 85:
        return "FULL  "
    else:
        return "GATE  "


def fetch_hourly_today():
    today_str = date.today().strftime("%Y-%m-%d")
    hourly = defaultdict(lambda: {"cost": 0.0, "output": 0})
    seen_request_ids = set()

    for jsonl_path in glob.glob(str(CLAUDE_DIR / "**" / "*.jsonl"), recursive=True):
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if obj.get("type") != "assistant":
                        continue

                    ts = obj.get("timestamp", obj.get("created_at", ""))
                    if not ts or ts[:10] != today_str:
                        continue

                    request_id = obj.get("requestId")
                    if request_id:
                        if request_id in seen_request_ids:
                            continue
                        seen_request_ids.add(request_id)

                    msg = obj.get("message", {})
                    usage = msg.get("usage", {}) or obj.get("usage", {})
                    if not usage:
                        continue

                    model = msg.get("model", obj.get("model", "unknown"))
                    if not model.startswith("claude-"):
                        model = f"claude-{model}"
                    rate = RATES.get(model, DEFAULT_RATE)

                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    cr  = usage.get("cache_read_input_tokens", 0)
                    cw  = usage.get("cache_creation_input_tokens", 0)

                    cost = (
                        inp / 1_000_000 * rate["input"] +
                        out / 1_000_000 * rate["output"] +
                        cr  / 1_000_000 * rate["cache_read"] +
                        cw  / 1_000_000 * rate["cache_write"]
                    )

                    try:
                        dt_local = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
                        hour = dt_local.hour
                    except Exception:
                        continue

                    hourly[hour]["cost"] += cost
                    hourly[hour]["output"] += out
        except Exception:
            continue

    return hourly


# ── Reset timing ──────────────────────────────────────────────────────────────

def get_reset_datetimes(next_reset: date):
    """
    Returns (all_models_reset_dt, sonnet_reset_dt) as local datetimes.

    All-models: noon on next_reset day (Saturday 12pm PT)
    Sonnet:     2am on next_reset + 1 day (Sunday 2am PT, 14h later)
    """
    base = datetime(next_reset.year, next_reset.month, next_reset.day)
    all_models_dt = base + timedelta(hours=ALL_MODELS_RESET_HOUR)
    sonnet_dt     = base + timedelta(hours=SONNET_RESET_HOUR)
    return all_models_dt, sonnet_dt


def dead_zone_status(next_reset: date):
    """
    Returns (in_dead_zone, hours_to_all_models_reset, label).
    Dead zone = after all-models resets but before Sonnet resets (14h window).
    """
    now = datetime.now()
    all_models_dt, sonnet_dt = get_reset_datetimes(next_reset)

    in_dead_zone = all_models_dt <= now < sonnet_dt
    hours_to_all_models = (all_models_dt - now).total_seconds() / 3600

    if in_dead_zone:
        hours_remaining = (sonnet_dt - now).total_seconds() / 3600
        label = f"DEAD ZONE  all-models reset, sonnet still live ({hours_remaining:.1f}h remaining)"
    elif hours_to_all_models < 0:
        label = "both reset"
    elif hours_to_all_models < 24:
        label = f"all-models resets in {hours_to_all_models:.1f}h  |  sonnet resets {hours_to_all_models+DEAD_ZONE_HOURS:.1f}h after"
    else:
        all_label = all_models_dt.strftime("%b %d %I%p").replace(" 0", " ").lower()
        son_label  = sonnet_dt.strftime("%b %d %I%p").replace(" 0", " ").lower()
        label = f"all-models {all_label}  |  sonnet {son_label}  |  {DEAD_ZONE_HOURS}h dead zone"

    return in_dead_zone, hours_to_all_models, label


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    weekly_quota, sonnet_quota, quota_cfg = load_quota_config()

    # --- Handle --calibrate flag ---
    if "--calibrate" in sys.argv:
        try:
            idx = sys.argv.index("--calibrate")
            claude_pct = float(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("Usage: python kpi_display.py --calibrate N [--sonnet-pct M]")
            sys.exit(1)

        sonnet_pct = None
        if "--sonnet-pct" in sys.argv:
            try:
                sidx = sys.argv.index("--sonnet-pct")
                sonnet_pct = float(sys.argv[sidx + 1])
            except (IndexError, ValueError):
                print("Usage: python kpi_display.py --calibrate N --sonnet-pct M")
                sys.exit(1)

        ccusage_data = fetch_ccusage_json(since_days=8)
        db_data = fetch_db_history()
        week_start = get_week_start()
        today_str = date.today().strftime("%Y-%m-%d")

        week_cost = 0.0
        sonnet_week_cost = 0.0
        for i in range(7):
            d = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
            if d > today_str:
                break
            if d in ccusage_data:
                week_cost        += ccusage_data[d]["totalCost"]
                sonnet_week_cost += model_cost_for_day(ccusage_data[d], "claude-sonnet")
            elif d in db_data:
                week_cost += db_data[d]["cost"]

        new_quota = week_cost / (claude_pct / 100.0)
        new_sonnet_quota = (
            sonnet_week_cost / (sonnet_pct / 100.0)
            if sonnet_pct is not None
            else sonnet_quota  # preserve existing
        )

        cfg = save_quota_config(new_quota, new_sonnet_quota, week_cost, claude_pct, sonnet_week_cost, sonnet_pct)
        print(f"Calibrated all-models: {claude_pct:.1f}% = ${week_cost:.2f}  ->  quota ~${new_quota:.0f}/week")
        if sonnet_pct is not None:
            print(f"Calibrated sonnet:     {sonnet_pct:.1f}% = ${sonnet_week_cost:.2f}  ->  quota ~${new_sonnet_quota:.0f}/week")
        else:
            print(f"Sonnet quota unchanged: ~${new_sonnet_quota:.0f}/week (pass --sonnet-pct M to recalibrate)")
        print(f"Saved to {CONFIG_PATH}")
        sys.exit(0)

    # --- Data ---
    today_str  = date.today().strftime("%Y-%m-%d")
    week_start = get_week_start()
    next_reset = week_start + timedelta(weeks=1)

    ccusage_data = fetch_ccusage_json(since_days=8)
    db_data      = fetch_db_history()

    # Today's cost
    if today_str in ccusage_data:
        today_cost = ccusage_data[today_str]["totalCost"]
        today_models = ccusage_data[today_str].get("modelsUsed", [])
        today_models_short = [
            m.replace("claude-", "").replace("-20251001", "").replace("-20250929", "")
            for m in today_models
        ]
    elif today_str in db_data:
        today_cost = db_data[today_str]["cost"]
        today_models_short = ["(from db)"]
    else:
        today_cost = 0.0
        today_models_short = ["no data yet"]

    today_ratio = today_cost / PLAN_DAILY_USD

    # 7-day rolling efficiency
    rolling_cost = 0.0
    days_counted = 0
    for i in range(7):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in ccusage_data:
            rolling_cost += ccusage_data[d]["totalCost"]
            days_counted += 1
        elif d in db_data:
            rolling_cost += db_data[d]["cost"]
            days_counted += 1
    rolling_ratio = rolling_cost / (PLAN_DAILY_USD * max(days_counted, 1))

    # Week spend — all-models and Sonnet-only
    week_cost        = 0.0
    sonnet_week_cost = 0.0
    for i in range(7):
        d = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
        if d > today_str:
            break
        if d in ccusage_data:
            week_cost        += ccusage_data[d]["totalCost"]
            sonnet_week_cost += model_cost_for_day(ccusage_data[d], "claude-sonnet")
        elif d in db_data:
            week_cost += db_data[d]["cost"]

    haiku_week_cost  = week_cost - sonnet_week_cost
    haiku_pct_of_week = (haiku_week_cost / week_cost * 100) if week_cost > 0 else 0.0

    # --- Quota utilization ---
    quota_pct        = week_cost        / weekly_quota * 100
    sonnet_quota_pct = sonnet_week_cost / sonnet_quota * 100

    # Binding = whichever cap is more constraining (higher %)
    binding_pct      = max(quota_pct, sonnet_quota_pct)
    binding_cap      = weekly_quota if quota_pct >= sonnet_quota_pct else sonnet_quota
    binding_label    = "all-models" if quota_pct >= sonnet_quota_pct else "sonnet"

    # Sprint room uses binding cap
    quota_gate_amt  = binding_cap * QUOTA_SPRINT_GATE
    quota_abort_amt = binding_cap * QUOTA_ABORT
    quota_sched     = weekly_quota * QUOTA_SCHED_RESERVE
    sprint_room     = max(quota_gate_amt - (week_cost if binding_label == "all-models" else sonnet_week_cost) - quota_sched, 0)

    # --- Spend pattern ---
    spend_pct = week_cost / WEEKLY_SPEND_BASELINE * 100

    # --- Pacing ---
    days_elapsed   = max((date.today() - week_start).days + 1, 1)
    days_remaining = 7 - days_elapsed

    smooth_days = min(days_elapsed, 3)
    smooth_costs = []
    for i in range(smooth_days):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in ccusage_data:
            smooth_costs.append(ccusage_data[d]["totalCost"])
        elif d in db_data:
            smooth_costs.append(db_data[d]["cost"])
        else:
            smooth_costs.append(0.0)
    smoothed_daily      = sum(smooth_costs) / len(smooth_costs) if smooth_costs else 0.0
    projected_cost      = week_cost + smoothed_daily * days_remaining
    projected_all_pct   = projected_cost / weekly_quota * 100
    # Estimate Sonnet fraction of projected spend
    sonnet_fraction     = (sonnet_week_cost / week_cost) if week_cost > 0 else 0.95
    projected_sonnet    = projected_cost * sonnet_fraction
    projected_sonnet_pct = projected_sonnet / sonnet_quota * 100
    projected_binding_pct = max(projected_all_pct, projected_sonnet_pct)

    # --- 7-day trend ---
    trend = []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        cost = 0.0
        if d in ccusage_data:
            cost = ccusage_data[d]["totalCost"]
        elif d in db_data:
            cost = db_data[d]["cost"]
        ratio = cost / PLAN_DAILY_USD
        trend.append((d, cost, ratio))
    max_trend_ratio = max((r for _, _, r in trend), default=1) or 1

    # --- Reset timing ---
    in_dead_zone, hrs_to_all_models_reset, reset_label = dead_zone_status(next_reset)

    calib_date = quota_cfg.get("calibrated_date", "unknown")

    # ── Output ────────────────────────────────────────────────────────────────
    SEP  = "  " + "-" * 60
    SEP2 = "  " + "." * 60

    print()
    print("  === QUOTA UTILIZATION  (Claude Max weekly allotment) ===")
    print(SEP)
    print(f"  ALL-MODELS   ${week_cost:6.2f}  of ~${weekly_quota:.0f}   [{bar(quota_pct, 100)}]  {quota_pct:5.1f}%  [{quota_status(quota_pct)}]")
    print(f"  SONNET-ONLY  ${sonnet_week_cost:6.2f}  of ~${sonnet_quota:.0f}   [{bar(sonnet_quota_pct, 100)}]  {sonnet_quota_pct:5.1f}%  [{quota_status(sonnet_quota_pct)}]")
    print(f"  HAIKU        ${haiku_week_cost:5.2f}   ({haiku_pct_of_week:.1f}% of week spend)")
    print(f"  BINDING CAP  {binding_label} ({binding_pct:.1f}% used)  |  gates use this cap")
    print(f"  SPRINT ROOM  ${sprint_room:6.2f}  before {QUOTA_SPRINT_GATE*100:.0f}% gate  (abort at {QUOTA_ABORT*100:.0f}%, sched reserve ${quota_sched:.2f})")

    if in_dead_zone:
        print(f"  !! {reset_label}")
    elif hrs_to_all_models_reset < 24:
        print(f"  ** RESET SOON  {reset_label}")
    else:
        print(f"  RESETS       {reset_label}")

    print(f"  CALIBRATED   {calib_date}  |  --calibrate N --sonnet-pct M to update")
    print()

    print("  === SPEND EFFICIENCY  (value per subscription dollar) ===")
    print(SEP)
    print(f"  TODAY        ${today_cost:6.2f}   ratio {today_ratio:5.1f}x   [{efficiency_status(today_ratio)}]")
    print(f"  7-DAY ROLL   ${rolling_cost:6.2f}   ratio {rolling_ratio:5.1f}x   [{efficiency_status(rolling_ratio)}]")
    print(f"  BASELINE     {RATIO_BASELINE}x  |  FLOOR {RATIO_FLOOR}x  |  ratio = API-equiv / plan-daily")
    print(f"  MODELS       {', '.join(today_models_short) if today_models_short else 'none'}")
    print()

    print("  === SPEND PATTERN  (vs ${:.0f}/wk historical avg) ===".format(WEEKLY_SPEND_BASELINE))
    print(SEP)
    smooth_label = f"{len(smooth_costs)}d avg"
    print(f"  WEEK SPEND   ${week_cost:6.2f}   Day {days_elapsed}/7  |  ${smoothed_daily:.2f}/day ({smooth_label})  [{spend_status(spend_pct)}]")
    print(f"  PROJECTED    ${projected_cost:.0f} by reset  =  {projected_all_pct:.0f}% all-models / {projected_sonnet_pct:.0f}% sonnet  [{trend_status(projected_binding_pct)}]")
    print(f"  WEEK START   {week_start.strftime('%Y-%m-%d')}")
    print()

    print("  7-DAY TREND                         ratio")
    print(SEP2)
    for d, cost, ratio in trend:
        b = bar(ratio, max(max_trend_ratio, RATIO_BASELINE * 1.1), width=20)
        marker = " <-- today" if d == today_str else ""
        print(f"  {d}  [{b}]  {ratio:5.1f}x{marker}")
    print()

    hourly = fetch_hourly_today()
    current_hour = datetime.now().hour
    max_hourly_cost = max((v["cost"] for v in hourly.values()), default=0.01) or 0.01
    print("  TODAY BY HOUR (24h local)")
    print(SEP)
    for h in range(24):
        hdata = hourly.get(h, {"cost": 0.0, "output": 0})
        cost_h = hdata["cost"]
        b = bar(cost_h, max_hourly_cost, width=18)
        now_marker = " <-- now" if h == current_hour else ""
        active = "*" if cost_h > 0 else " "
        print(f"  {active} {h:02d}  [{b}]  ${cost_h:.2f}{now_marker}")
    print()


if __name__ == "__main__":
    main()
