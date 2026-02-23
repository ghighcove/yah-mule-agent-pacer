"""
kpi_display_v2.py — Yah Mule CLI v2: full-screen live terminal layout.

Replaces rolling stdout with rich.live panels. Full terminal height, no scroll.

Usage:
    python kpi_display_v2.py              # live mode, 60s data refresh
    python kpi_display_v2.py --interval 30
    python kpi_display_v2.py --once       # single-shot output and exit
    python kpi_display_v2.py --calibrate N [--sonnet-pct M]
"""

import glob
import json
import sys
import time
import sqlite3
import subprocess
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    _RICH = True
except ImportError:
    _RICH = False

# ── Constants (mirror kpi_display.py) ─────────────────────────────────────────

DB_PATH     = Path("G:/ai/_data/analytics.db")
CLAUDE_DIR  = Path.home() / ".claude" / "projects"
CONFIG_PATH = Path(__file__).parent / "quota_config.json"

PLAN_DAILY_USD          = 100.0 / 30.0
RATIO_BASELINE          = 15.5
RATIO_FLOOR             = 12.0
WEEKLY_SPEND_BASELINE   = 55.0
WEEKLY_QUOTA_DEFAULT    = 607.0
WEEKLY_SONNET_QUOTA_DEFAULT = 789.0
QUOTA_SPRINT_GATE       = 0.80
QUOTA_ABORT             = 0.90
QUOTA_SCHED_RESERVE     = 0.05
ALL_MODELS_RESET_HOUR   = 12
SONNET_RESET_HOUR       = 26
DEAD_ZONE_HOURS         = SONNET_RESET_HOUR - ALL_MODELS_RESET_HOUR

RATES = {
    "claude-sonnet-4-6":            {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5":             {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-opus-4-6":              {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-5":            {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5-20251001":    {"input": 0.80,  "output": 4.00,  "cache_write": 1.00,  "cache_read": 0.08},
    "claude-sonnet-4-5-20250929":   {"input": 3.00,  "output": 15.00, "cache_write": 3.75,  "cache_read": 0.30},
}
DEFAULT_RATE = {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30}


# ── Data functions (same logic as kpi_display.py) ─────────────────────────────

def load_quota_config():
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
            return (
                cfg.get("weekly_quota_usd_equiv",        WEEKLY_QUOTA_DEFAULT),
                cfg.get("weekly_sonnet_quota_usd_equiv", WEEKLY_SONNET_QUOTA_DEFAULT),
                cfg,
            )
        except Exception:
            pass
    return WEEKLY_QUOTA_DEFAULT, WEEKLY_SONNET_QUOTA_DEFAULT, {}


def get_week_start():
    today = date.today()
    anchor = date(2026, 2, 7)
    days = (today - anchor).days
    return anchor + timedelta(weeks=days // 7)


def fetch_ccusage_json(since_days=8):
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


def model_cost_for_day(day_data, model_prefix):
    if not day_data:
        return 0.0
    return sum(
        b.get("cost", 0.0)
        for b in day_data.get("modelBreakdowns", [])
        if b.get("modelName", "").startswith(model_prefix)
    )


def fetch_db_history():
    if not DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(DB_PATH)
        cutoff = (date.today() - timedelta(days=14)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT date, api_cost_usd, efficiency_ratio FROM efficiency_daily WHERE date >= ? ORDER BY date",
            (cutoff,)
        ).fetchall()
        conn.close()
        return {r[0]: {"cost": r[1], "ratio": r[2]} for r in rows}
    except Exception:
        return {}


def get_reset_datetimes(next_reset):
    base = datetime(next_reset.year, next_reset.month, next_reset.day)
    return (
        base + timedelta(hours=ALL_MODELS_RESET_HOUR),
        base + timedelta(hours=SONNET_RESET_HOUR),
    )


def dead_zone_status(next_reset):
    now = datetime.now()
    all_dt, son_dt = get_reset_datetimes(next_reset)
    in_dead = all_dt <= now < son_dt
    hrs_to_all = (all_dt - now).total_seconds() / 3600
    if in_dead:
        hrs_rem = (son_dt - now).total_seconds() / 3600
        label = f"DEAD ZONE  all-models reset, sonnet still live ({hrs_rem:.1f}h remaining)"
    elif hrs_to_all < 0:
        label = "both reset"
    elif hrs_to_all < 24:
        label = f"all-models resets in {hrs_to_all:.1f}h  |  sonnet in {hrs_to_all + DEAD_ZONE_HOURS:.1f}h"
    else:
        all_l = all_dt.strftime("%b %d %I%p").lower()
        son_l = son_dt.strftime("%b %d %I%p").lower()
        label = f"all-models {all_l}  |  sonnet {son_l}  |  {DEAD_ZONE_HOURS}h dead zone"
    return in_dead, hrs_to_all, label


def fetch_hourly_today():
    today_str = date.today().strftime("%Y-%m-%d")
    hourly = defaultdict(lambda: {"cost": 0.0})
    seen = set()
    for path in glob.glob(str(CLAUDE_DIR / "**" / "*.jsonl"), recursive=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
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
                    rid = obj.get("requestId")
                    if rid:
                        if rid in seen:
                            continue
                        seen.add(rid)
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
                        hour = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().hour
                    except Exception:
                        continue
                    hourly[hour]["cost"] += cost
        except Exception:
            continue
    return hourly


# ── Color helpers ──────────────────────────────────────────────────────────────

def quota_color(pct):
    if pct >= QUOTA_ABORT * 100:     return "red"
    if pct >= QUOTA_SPRINT_GATE * 100: return "yellow"
    return "green"

def ratio_color(ratio):
    if ratio >= RATIO_BASELINE: return "green"
    if ratio >= RATIO_FLOOR:    return "yellow"
    return "red"

def spend_color(pct):
    if pct >= 130: return "red"
    if pct >= 75:  return "yellow"
    return "green"

def trend_color(proj_pct):
    if proj_pct >= 85: return "red"
    if proj_pct >= 65: return "yellow"
    return "green"

def rich_bar(value, max_val, width=18, fill="█", empty="░"):
    if max_val <= 0:
        return empty * width
    filled = int(round(min(value / max_val, 1.0) * width))
    return fill * filled + empty * (width - filled)


# ── Data bundle ───────────────────────────────────────────────────────────────

def fetch_all():
    weekly_quota, sonnet_quota, quota_cfg = load_quota_config()
    today_str  = date.today().strftime("%Y-%m-%d")
    week_start = get_week_start()
    next_reset = week_start + timedelta(weeks=1)

    cc = fetch_ccusage_json(since_days=8)
    db = fetch_db_history()

    # Today
    if today_str in cc:
        today_cost = cc[today_str]["totalCost"]
        today_models = [
            m.replace("claude-", "").replace("-20251001", "").replace("-20250929", "")
            for m in cc[today_str].get("modelsUsed", [])
        ]
    elif today_str in db:
        today_cost = db[today_str]["cost"]
        today_models = ["(db)"]
    else:
        today_cost, today_models = 0.0, ["no data"]

    # 7-day rolling efficiency
    rolling_cost, days_counted = 0.0, 0
    for i in range(7):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in cc:
            rolling_cost += cc[d]["totalCost"]; days_counted += 1
        elif d in db:
            rolling_cost += db[d]["cost"];      days_counted += 1
    rolling_ratio = rolling_cost / (PLAN_DAILY_USD * max(days_counted, 1))

    # Week totals
    week_cost = sonnet_week_cost = 0.0
    for i in range(7):
        d = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
        if d > today_str:
            break
        if d in cc:
            week_cost        += cc[d]["totalCost"]
            sonnet_week_cost += model_cost_for_day(cc[d], "claude-sonnet")
        elif d in db:
            week_cost += db[d]["cost"]

    haiku_week_cost    = week_cost - sonnet_week_cost
    haiku_pct_of_week  = (haiku_week_cost / week_cost * 100) if week_cost > 0 else 0.0
    quota_pct          = week_cost        / weekly_quota * 100
    sonnet_quota_pct   = sonnet_week_cost / sonnet_quota * 100
    binding_pct        = max(quota_pct, sonnet_quota_pct)
    binding_label      = "all-models" if quota_pct >= sonnet_quota_pct else "sonnet"
    binding_cap        = weekly_quota if binding_label == "all-models" else sonnet_quota
    quota_sched        = weekly_quota * QUOTA_SCHED_RESERVE
    sprint_room        = max(
        binding_cap * QUOTA_SPRINT_GATE
        - (week_cost if binding_label == "all-models" else sonnet_week_cost)
        - quota_sched, 0
    )
    spend_pct          = week_cost / WEEKLY_SPEND_BASELINE * 100

    # Pacing
    days_elapsed   = max((date.today() - week_start).days + 1, 1)
    days_remaining = 7 - days_elapsed
    smooth_n       = min(days_elapsed, 3)
    smooth_costs   = []
    for i in range(smooth_n):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in cc:   smooth_costs.append(cc[d]["totalCost"])
        elif d in db: smooth_costs.append(db[d]["cost"])
        else:         smooth_costs.append(0.0)
    smoothed_daily       = sum(smooth_costs) / len(smooth_costs) if smooth_costs else 0.0
    projected_cost       = week_cost + smoothed_daily * days_remaining
    projected_all_pct    = projected_cost / weekly_quota * 100
    sonnet_fraction      = (sonnet_week_cost / week_cost) if week_cost > 0 else 0.95
    projected_sonnet_pct = projected_cost * sonnet_fraction / sonnet_quota * 100
    projected_binding    = max(projected_all_pct, projected_sonnet_pct)

    # 7-day trend
    trend = []
    for i in range(6, -1, -1):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        cost = cc[d]["totalCost"] if d in cc else (db[d]["cost"] if d in db else 0.0)
        trend.append((d, cost, cost / PLAN_DAILY_USD))
    max_trend_ratio = max((r for _, _, r in trend), default=1) or 1

    in_dead, hrs_all, reset_label = dead_zone_status(next_reset)
    hourly = fetch_hourly_today()

    return dict(
        today_cost=today_cost, today_models=today_models,
        today_ratio=today_cost / PLAN_DAILY_USD,
        rolling_cost=rolling_cost, rolling_ratio=rolling_ratio,
        week_cost=week_cost, sonnet_week_cost=sonnet_week_cost,
        haiku_pct_of_week=haiku_pct_of_week,
        quota_pct=quota_pct, sonnet_quota_pct=sonnet_quota_pct,
        binding_pct=binding_pct, binding_label=binding_label,
        sprint_room=sprint_room, spend_pct=spend_pct,
        days_elapsed=days_elapsed, days_remaining=days_remaining,
        smoothed_daily=smoothed_daily, smooth_n=smooth_n,
        projected_cost=projected_cost, projected_all_pct=projected_all_pct,
        projected_sonnet_pct=projected_sonnet_pct, projected_binding=projected_binding,
        trend=trend, max_trend_ratio=max_trend_ratio,
        in_dead=in_dead, hrs_all=hrs_all, reset_label=reset_label,
        hourly=hourly, week_start=week_start, today_str=today_str,
        weekly_quota=weekly_quota, sonnet_quota=sonnet_quota,
        calib_date=quota_cfg.get("calibrated_date", "unknown"),
    )


# ── Panel builders ────────────────────────────────────────────────────────────

def panel_quota(d):
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=14)
    t.add_column()
    t.add_column(width=22)
    t.add_column(width=7, justify="right")
    t.add_column(width=10)

    qc = quota_color(d["quota_pct"])
    sc = quota_color(d["sonnet_quota_pct"])
    t.add_row(
        "ALL-MODELS",
        f"${d['week_cost']:6.2f} / ~${d['weekly_quota']:.0f}",
        f"[{qc}]{rich_bar(d['quota_pct'], 100)}[/]",
        f"{d['quota_pct']:5.1f}%",
        f"[{qc}]{'PROTECT' if d['quota_pct'] >= 90 else 'GATE   ' if d['quota_pct'] >= 80 else 'OPEN   '}[/]",
    )
    t.add_row(
        "SONNET-ONLY",
        f"${d['sonnet_week_cost']:6.2f} / ~${d['sonnet_quota']:.0f}",
        f"[{sc}]{rich_bar(d['sonnet_quota_pct'], 100)}[/]",
        f"{d['sonnet_quota_pct']:5.1f}%",
        f"[{sc}]{'PROTECT' if d['sonnet_quota_pct'] >= 90 else 'GATE   ' if d['sonnet_quota_pct'] >= 80 else 'OPEN   '}[/]",
    )
    t.add_row(
        "HAIKU",
        f"{d['haiku_pct_of_week']:.1f}% of week", "", "", "",
    )
    t.add_row(
        "BINDING",
        f"[bold]{d['binding_label']}[/] ({d['binding_pct']:.1f}% used)", "", "", "",
    )
    t.add_row(
        "SPRINT ROOM",
        f"[green]${d['sprint_room']:.2f}[/] before 80% gate", "", "", "",
    )

    rc = "red" if d["in_dead"] else ("yellow" if d["hrs_all"] < 24 else "dim")
    prefix = "!! " if d["in_dead"] else ("** " if d["hrs_all"] < 24 else "   ")
    t.add_row("RESETS", f"[{rc}]{prefix}{d['reset_label']}[/]", "", "", "")
    t.add_row("CALIBRATED", d["calib_date"], "", "", "")

    return Panel(t, title="[cyan]QUOTA UTILIZATION[/]", border_style="cyan", padding=(0, 1))


def panel_efficiency(d):
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=12)
    t.add_column(width=10)
    t.add_column(width=10)
    t.add_column(width=10)

    tc = ratio_color(d["today_ratio"])
    rc = ratio_color(d["rolling_ratio"])
    t.add_row(
        "TODAY",
        f"${d['today_cost']:.2f}",
        f"[{tc}]{d['today_ratio']:5.1f}x[/]",
        f"[{tc}]{'ON    ' if d['today_ratio'] >= RATIO_BASELINE else 'BELOW ' if d['today_ratio'] >= RATIO_FLOOR else 'LOW   '}[/]",
    )
    t.add_row(
        "7-DAY ROLL",
        f"${d['rolling_cost']:.2f}",
        f"[{rc}]{d['rolling_ratio']:5.1f}x[/]",
        f"[{rc}]{'ON    ' if d['rolling_ratio'] >= RATIO_BASELINE else 'BELOW ' if d['rolling_ratio'] >= RATIO_FLOOR else 'LOW   '}[/]",
    )
    t.add_row("BASELINE", f"{RATIO_BASELINE}x", "FLOOR", f"{RATIO_FLOOR}x")
    t.add_row("MODELS", ", ".join(d["today_models"][:3]) or "none", "", "")
    return Panel(t, title="[cyan]SPEND EFFICIENCY[/]", border_style="cyan", padding=(0, 1))


def panel_pattern(d):
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=12)
    t.add_column()

    sc = spend_color(d["spend_pct"])
    pc = trend_color(d["projected_binding"])
    t.add_row(
        "WEEK SPEND",
        f"[{sc}]${d['week_cost']:.2f}[/]  Day {d['days_elapsed']}/7  |  "
        f"${d['smoothed_daily']:.2f}/day ({d['smooth_n']}d avg)  "
        f"[{sc}]{'HEAVY' if d['spend_pct'] >= 130 else 'HIGH ' if d['spend_pct'] >= 75 else 'NORMAL'}[/]",
    )
    t.add_row(
        "PROJECTED",
        f"[{pc}]${d['projected_cost']:.0f}[/] by reset  =  "
        f"{d['projected_all_pct']:.0f}% all-models / {d['projected_sonnet_pct']:.0f}% sonnet  "
        f"[{pc}]{'GATE' if d['projected_binding'] >= 85 else 'FULL' if d['projected_binding'] >= 65 else 'GOOD' if d['projected_binding'] >= 30 else 'LIGHT'}[/]",
    )
    t.add_row("WEEK START", d["week_start"].strftime("%Y-%m-%d"), )
    return Panel(t, title="[cyan]SPEND PATTERN[/]", border_style="cyan", padding=(0, 1))


def panel_trend(d):
    t = Table.grid(padding=(0, 1))
    t.add_column(style="dim", width=12)
    t.add_column(width=22)
    t.add_column(width=8, justify="right")

    scale = max(d["max_trend_ratio"], RATIO_BASELINE * 1.1)
    for day, cost, ratio in d["trend"]:
        rc = ratio_color(ratio)
        marker = " ← today" if day == d["today_str"] else ""
        t.add_row(
            day,
            f"[{rc}]{rich_bar(ratio, scale, width=20)}[/]",
            f"[{rc}]{ratio:5.1f}x[/]{marker}",
        )
    return Panel(t, title="[cyan]7-DAY TREND[/]", border_style="cyan", padding=(0, 1))


def panel_hourly(d):
    hourly = d["hourly"]
    current_hour = datetime.now().hour
    active_hours = [h for h in range(24) if hourly.get(h, {}).get("cost", 0) > 0 or h == current_hour]
    if not active_hours:
        active_hours = [current_hour]

    max_cost = max((hourly.get(h, {}).get("cost", 0) for h in range(24)), default=0.01) or 0.01

    t = Table.grid(padding=(0, 1))
    t.add_column(width=4, style="dim")
    t.add_column(width=20)
    t.add_column(width=8)

    for h in range(24):
        cost_h = hourly.get(h, {}).get("cost", 0.0)
        if cost_h == 0 and h != current_hour:
            continue
        now_mark = " [yellow]← now[/]" if h == current_hour else ""
        color = "yellow" if h == current_hour and cost_h == 0 else ("green" if cost_h > 0 else "dim")
        t.add_row(
            f"{h:02d}h",
            f"[{color}]{rich_bar(cost_h, max_cost, width=18)}[/]",
            f"[{color}]${cost_h:.2f}[/]{now_mark}",
        )
    return Panel(t, title="[cyan]TODAY BY HOUR[/]", border_style="cyan", padding=(0, 1))


# ── Layout builder ────────────────────────────────────────────────────────────

def build_layout(d, ts):
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=1),
        Layout(name="top_row", size=11),
        Layout(name="pattern", size=7),
        Layout(name="trend",   size=11),
        Layout(name="hourly"),
    )
    layout["top_row"].split_row(
        Layout(name="quota",      ratio=3),
        Layout(name="efficiency", ratio=2),
    )

    layout["header"].update(
        Text(
            f"  YAH MULE — Claude Efficiency Monitor       {ts}",
            style="bold cyan",
        )
    )
    layout["quota"].update(panel_quota(d))
    layout["efficiency"].update(panel_efficiency(d))
    layout["pattern"].update(panel_pattern(d))
    layout["trend"].update(panel_trend(d))
    layout["hourly"].update(panel_hourly(d))

    return layout


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # --calibrate passthrough — delegate to kpi_display.py
    if "--calibrate" in sys.argv:
        import subprocess as sp
        script = Path(__file__).parent / "kpi_display.py"
        sp.run([sys.executable, str(script)] + sys.argv[1:])
        return

    if not _RICH:
        print("rich not installed. Run: pip install rich", file=sys.stderr)
        sys.exit(1)

    # --interval
    interval = 60
    if "--interval" in sys.argv:
        try:
            interval = int(sys.argv[sys.argv.index("--interval") + 1])
        except (IndexError, ValueError):
            pass

    # --once: single-shot, no live loop
    once = "--once" in sys.argv

    console = Console()

    if once:
        d = fetch_all()
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        console.print(build_layout(d, ts))
        return

    # Full-screen live mode
    d = fetch_all()
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    last_fetch = time.monotonic()

    with Live(
        build_layout(d, ts),
        screen=True,
        console=console,
        refresh_per_second=1,
    ) as live:
        while True:
            time.sleep(1)
            ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
            now = time.monotonic()
            if now - last_fetch >= interval:
                d = fetch_all()
                last_fetch = now
            live.update(build_layout(d, ts))


if __name__ == "__main__":
    main()
