"""
kpi_display_v2.py — Yah Mule CLI v2: full-screen live terminal layout.

Replaces rolling stdout with rich.live panels. Full terminal height, no scroll.
Run via yah_mule.py (unified entry point) or directly.

Usage:
    python yah_mule.py                    # preferred — unified launcher
    python kpi_display_v2.py              # direct: live mode, 300s data refresh
    python kpi_display_v2.py --interval 60
    python kpi_display_v2.py --once       # single-shot output and exit
    python kpi_display_v2.py --calibrate N [--sonnet-pct M]
    python kpi_display_v2.py --profile    # log fetch/render timing to yah_mule_profile.log
"""

__version__ = "2.6.0"

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

try:
    import psutil as _psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

# ── Profiling (--profile flag) ─────────────────────────────────────────────────

_profile_path = Path(__file__).parent / "yah_mule_profile.log"
_profile_fh = None   # set to open file handle when --profile is active


def _prof_start(label):
    """Return (label, rss_mb, t0) token if profiling active, else None."""
    if _profile_fh is None:
        return None
    rss = _psutil.Process().memory_info().rss // (1024 * 1024) if _PSUTIL else 0
    return (label, rss, time.monotonic())


def _prof_end(tok):
    """Write one timing line to profile log. No-op if tok is None."""
    if tok is None or _profile_fh is None:
        return
    label, rss_b, t0 = tok
    elapsed = (time.monotonic() - t0) * 1000
    rss_a = _psutil.Process().memory_info().rss // (1024 * 1024) if _PSUTIL else 0
    ts_str = datetime.now().strftime("%H:%M:%S")
    _profile_fh.write(
        f"{ts_str}  {label:<22}  {elapsed:8.1f}ms  rss {rss_b}→{rss_a}MB\n"
    )
    _profile_fh.flush()

# ── Constants (mirror kpi_display.py) ─────────────────────────────────────────

DB_PATH     = Path(__file__).parent / "usage_data.db"
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
ALL_MODELS_RESET_HOUR   = 20    # 8pm PT (Anthropic unified reset 2026-02-26)
SONNET_RESET_HOUR       = 20    # 8pm PT — same as all-models, no dead zone
DEAD_ZONE_HOURS         = 0     # dead zone eliminated

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
    anchor = date(2026, 2, 26)  # Anthropic early-reset 2026-02-26; new cycle = Thu 8pm PT
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
                    if not ts:
                        continue
                    try:
                        ts_local_date = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
                    except Exception:
                        continue
                    if ts_local_date != today_str:
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


# ── Smokestack constants ───────────────────────────────────────────────────────

STACK_BODY_H  = 6   # rows of chimney body
STACK_W       = 7   # inner fill width (chars between | |)
STACK_SMOKE_H = 2   # rows above chimney opening for overflow smoke

# ── Hourglass & Sparkline constants ───────────────────────────────────────────

SPARK_CHARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"  # ▁▂▃▄▅▆▇█
HG_BODY_H   = 3   # rows per half of hourglass (top + bottom)

def _stack_color(ratio):
    """Shared heat-map color for both reactor stacks and hourly bars."""
    if ratio >= 1.4:  return "magenta"
    if ratio >= 1.2:  return "purple"
    if ratio >= 1.0:  return "bright_red"
    if ratio >= 0.9:  return "bright_green"
    if ratio >= 0.6:  return "green"
    if ratio >= 0.3:  return "cyan"
    return "dim"


def _hourly_sparkline(hourly, current_hour, max_cost):
    """
    Single-line rich Text sparkline covering hours 0-23.
    Current hour is bracketed in yellow. Colors relative to day average.
    """
    spent_h = [h for h in range(24) if hourly.get(h, {}).get("cost", 0) > 0]
    total   = sum(hourly.get(h, {}).get("cost", 0) for h in spent_h)
    avg     = total / len(spent_h) if spent_h else 0.0

    text = Text()
    for h in range(24):
        cost = hourly.get(h, {}).get("cost", 0.0)
        if max_cost > 0 and cost > 0:
            level = min(int(cost / max_cost * 7) + 1, 8)
        else:
            level = 0
        char = SPARK_CHARS[level]
        if h == current_hour:
            text.append("[", style="yellow")
            col = _stack_color(cost / avg) if (cost > 0 and avg > 0) else "yellow"
            text.append(char, style=col)
            text.append("]", style="yellow")
        else:
            col = _stack_color(cost / avg) if (cost > 0 and avg > 0) else "dim"
            text.append(char, style=col)
    return text


def render_hourglass(minutes_elapsed, cost_this_hour, avg_hour):
    """
    10-line ASCII hourglass for current hour.
    Top half empties (# sand), bottom half fills (. sand) as minutes pass (0-59).
    Color = current-hour burn rate vs day average.
    Returns list of exactly 10 rich Text lines (matches render_stack / render_mule).

    Line layout: border / top-fill×3 / waist×2 / bot-fill×3 / label = 10
    """
    p = min(minutes_elapsed / 59.0, 1.0) if minutes_elapsed > 0 else 0.0

    if avg_hour > 0 and cost_this_hour > 0 and minutes_elapsed > 0:
        projected_h = cost_this_hour / (minutes_elapsed / 60.0)
        color = _stack_color(projected_h / avg_hour)
    elif cost_this_hour > 0:
        color = "green"
    else:
        color = "yellow"   # no spend this hour yet

    W = STACK_W   # 7 — same inner width as smokestack

    top_filled = round((1.0 - p) * HG_BODY_H)   # 3 at :00 → 0 near :59
    bot_filled = round(p * HG_BODY_H)            # 0 at :00 → 3 near :59

    # Fill widths: top widens at top, bottom widens at bottom
    top_widths = [7, 5, 3]   # row 0=top(widest), row 2=narrowest
    bot_widths = [3, 5, 7]   # row 0=narrowest,   row 2=bottom(widest)

    lines = []

    # Line 0: top border
    lines.append(Text(f"/{'-' * W}\\", style="dim"))

    # Lines 1-3: top half (i=0 is widest; i < top_filled = sand still present)
    for i in range(HG_BODY_H):
        w   = top_widths[i]
        pad = (W - w) // 2
        if i < top_filled:
            fill = " " * pad + "#" * w + " " * (W - w - pad)
            lines.append(Text(f"|{fill}|", style=color))
        else:
            lines.append(Text(f"|{' ' * W}|", style="dim"))

    # Lines 4-5: waist
    waist = "-" * (W - 2)
    lines.append(Text(f" \\{waist}/ ", style="dim"))
    lines.append(Text(f" /{waist}\\ ", style="dim"))

    # Lines 6-8: bottom half (i=0 is narrowest; i >= HG_BODY_H-bot_filled = sand arrived)
    for i in range(HG_BODY_H):
        w   = bot_widths[i]
        pad = (W - w) // 2
        if i >= (HG_BODY_H - bot_filled):
            fill = " " * pad + "." * w + " " * (W - w - pad)
            lines.append(Text(f"|{fill}|", style=color))
        else:
            lines.append(Text(f"|{' ' * W}|", style="dim"))

    # Line 9: time label (minute elapsed + projected $/h if any spend)
    elapsed_str = f":{minutes_elapsed:02d}"
    if cost_this_hour > 0 and minutes_elapsed > 0:
        pace  = cost_this_hour / (minutes_elapsed / 60.0)
        label = f"{elapsed_str} ${pace:.1f}/h"
    else:
        label = elapsed_str
    lines.append(Text(f"{label:^{W + 2}}", style=color))

    return lines   # always 1 + 3 + 2 + 3 + 1 = 10 lines


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
        marker = " <- today" if day == d["today_str"] else ""
        t.add_row(
            day,
            f"[{rc}]{rich_bar(ratio, scale, width=20)}[/]",
            f"[{rc}]{ratio:5.1f}x[/]{marker}",
        )
    return Panel(t, title="[cyan]7-DAY TREND[/]", border_style="cyan", padding=(0, 1))


def panel_hourly(d):
    """
    TODAY BY HOUR panel — redesigned v2.2:
      Row 1: 24-hour sparkline (all hours at a glance, current = [X])
      Row 2: Stats — peak hour (★), avg $/h, current-hour pace
      Row 3: Separator
      Row 4+: Active hours list — current hour FIRST (always visible),
              then other active hours ascending; pre-dawn (0-6h) dimmed;
              peak hour marked ★
    """
    hourly       = d["hourly"]
    now          = datetime.now()
    current_hour = now.hour
    elapsed_min  = now.minute

    spent_hours = [h for h in range(24) if hourly.get(h, {}).get("cost", 0) > 0]
    avg_hour    = d["today_cost"] / len(spent_hours) if spent_hours else 0.0
    max_cost    = max((hourly.get(h, {}).get("cost", 0) for h in range(24)), default=0.01) or 0.01

    # Peak hour
    peak_hour = max(range(24), key=lambda h: hourly.get(h, {}).get("cost", 0))
    peak_cost = hourly.get(peak_hour, {}).get("cost", 0)

    # Current hour projected pace
    cost_this_hour = hourly.get(current_hour, {}).get("cost", 0.0)
    pace_per_hour  = (cost_this_hour / (elapsed_min / 60.0)) if (cost_this_hour > 0 and elapsed_min > 0) else 0.0

    t = Table.grid(padding=(0, 1))
    t.add_column(width=6, style="dim")   # hour label
    t.add_column(width=26)               # sparkline / bar
    t.add_column(width=12)               # cost / annotation

    # Row 1: sparkline (all 24 hours)
    sparkline = _hourly_sparkline(hourly, current_hour, max_cost)
    t.add_row("[dim]00-23[/]", sparkline, "")

    # Row 2: stats
    stats_parts = []
    if peak_cost > 0:
        stats_parts.append(f"[yellow]★[/] peak [dim]{peak_hour:02d}h[/] ${peak_cost:.2f}")
    if avg_hour > 0:
        stats_parts.append(f"[dim]avg ${avg_hour:.2f}/h[/]")
    if pace_per_hour > 0 and avg_hour > 0:
        pc = _stack_color(pace_per_hour / avg_hour)
        stats_parts.append(f"[{pc}]pace ${pace_per_hour:.2f}/h[/]")
    stats_str = "  ".join(stats_parts) if stats_parts else "[dim]no spend yet[/]"
    t.add_row("", stats_str, "")

    # Row 3: separator
    t.add_row(
        "[dim]------[/]",
        "[dim]" + "-" * 26 + "[/]",
        "[dim]------------[/]",
    )

    # Rows 4+: current hour first, then other active hours ascending
    DEAD_END = 7   # hours 0-6 = pre-dawn, shown dim
    active_others = [h for h in range(24)
                     if h != current_hour and hourly.get(h, {}).get("cost", 0) > 0]
    display_hours = [current_hour] + active_others

    for h in display_hours:
        cost_h  = hourly.get(h, {}).get("cost", 0.0)
        is_dead = (h < DEAD_END and h != current_hour)
        is_peak = (h == peak_hour and peak_cost > 0)

        now_mark  = " [yellow]<- now[/]" if h == current_hour else ""
        peak_mark = " [yellow]*[/]" if is_peak else ""

        if is_dead:
            color = "dim"
        elif h == current_hour and cost_h == 0:
            color = "yellow"
        elif cost_h > 0 and avg_hour > 0:
            color = _stack_color(cost_h / avg_hour)
        elif cost_h > 0:
            color = "green"
        else:
            color = "dim"

        t.add_row(
            f"{h:02d}h",
            f"[{color}]{rich_bar(cost_h, max_cost, width=24)}[/]{peak_mark}",
            f"[{color}]${cost_h:.2f}[/]{now_mark}",
        )

    return Panel(t, title="[cyan]TODAY BY HOUR[/]", border_style="cyan", padding=(0, 1))


def render_stack(value, target, val_fmt="{:.1f}"):
    """
    Returns a list of rich Text lines (top->bottom) for one ASCII smokestack.
    Total lines = STACK_SMOKE_H + STACK_BODY_H + 2  (base row + value label).
    Fill from bottom; top of body = 100% of target ("just right" marker).
    Overflow above target spills into smoke rows.
    """
    ratio    = (value / target) if target > 0 else 0.0
    overflow = max(0.0, ratio - 1.0)
    color    = _stack_color(ratio)
    W        = STACK_W
    lines    = []

    # ── Smoke rows (shown above chimney when overflow > 0) ──
    for s in range(STACK_SMOKE_H):
        tier      = STACK_SMOKE_H - 1 - s        # 0 = closest to chimney
        threshold = tier * 0.2                    # tier=0 -> any overflow; tier=1 -> >20% overflow
        if overflow > threshold:
            smoke_w = min(int(overflow * W * 1.5) + tier, W - 1)
            smoke   = ("@" * smoke_w).center(W)
            sc      = "magenta" if tier > 0 else "bright_red"
            lines.append(Text(f"({smoke})", style=sc))
        else:
            lines.append(Text(f" {' ' * W} ", style="dim"))

    # ── Chimney body (top row = "just right" marker, fill from bottom) ──
    filled_rows = min(int(ratio * STACK_BODY_H), STACK_BODY_H)
    empty_rows  = STACK_BODY_H - filled_rows

    for i in range(STACK_BODY_H):
        is_filled = (i >= empty_rows)
        if i == 0:                          # top of body = target line
            lines.append(Text(f"|{'-' * W}|", style="yellow" if is_filled else "dim"))
        elif is_filled:
            lines.append(Text(f"|{'#' * W}|", style=color))
        else:
            lines.append(Text(f"|{' ' * W}|", style="dim"))

    lines.append(Text(f"/{'=' * W}\\", style="dim"))
    val_str = val_fmt.format(value)
    lines.append(Text(f"{val_str:^{W + 2}}", style=color))

    return lines   # always STACK_SMOKE_H + STACK_BODY_H + 2 = 10 lines


def render_mule(projected_pct):
    """
    10-line ASCII mule, colored by projected end-of-week quota risk.
    green = GOOD (<65%), yellow = FULL (65-84%), red = GATE (85%+).
    """
    color  = trend_color(projected_pct)
    health = "GOOD" if projected_pct < 65 else ("FULL" if projected_pct < 85 else "GATE")
    lines = [
        "          ",
        "   |\\     ",
        "  (|_\\    ",
        "  (oo )~~ ",
        "   \\__/   ",
        "    ||    ",
        "   /||\\   ",
        "  / || \\  ",
        " /__|  |__",
        f"  {health:^8}",
    ]
    return [Text(line, style=color) for line in lines]


def panel_smokestacks(d):
    """
    REACTOR panel — 4 columns: EFF stack | PROJ stack | mule | hourglass
    Hourglass (v2.2): ASCII hourglass for current hour, top empties / bottom fills.
    """
    hourly = d["hourly"]
    now    = datetime.now()

    spent_hours    = [h for h in range(24) if hourly.get(h, {}).get("cost", 0) > 0]
    avg_hour       = d["today_cost"] / len(spent_hours) if spent_hours else 0.0
    cost_this_hour = hourly.get(now.hour, {}).get("cost", 0.0)

    eff_lines  = render_stack(d["today_ratio"],       RATIO_BASELINE,          val_fmt="EFF {:.1f}x")
    pace_lines = render_stack(d["projected_binding"], QUOTA_SPRINT_GATE * 100, val_fmt="PROJ {:.0f}%")
    mule_lines = render_mule(d["projected_binding"])
    hg_lines   = render_hourglass(now.minute, cost_this_hour, avg_hour)

    t = Table.grid(padding=(0, 3))
    t.add_column(width=STACK_W + 2)   # EFF stack
    t.add_column(width=STACK_W + 2)   # PROJ stack
    t.add_column(width=12)            # mule
    t.add_column(width=STACK_W + 2)   # hourglass

    for left, right, mule, hg in zip(eff_lines, pace_lines, mule_lines, hg_lines):
        t.add_row(left, right, mule, hg)

    return Panel(
        t,
        title="[cyan]REACTOR[/]",
        subtitle="[dim]-- = target  @@ = overflow  :MM = hour elapsed  |  mule = projected risk[/]",
        border_style="cyan",
        padding=(0, 2),
    )


# ── Layout builder ────────────────────────────────────────────────────────────

def build_layout(d, ts):
    layout = Layout()
    layout.split_column(
        Layout(name="header",      size=1),
        Layout(name="top_row",     size=9),    # quota(7+2) / efficiency(4+2) -> max=9
        Layout(name="pattern",     size=5),    # 3 rows + 2 border
        Layout(name="trend",       size=9),    # 7 rows + 2 border
        Layout(name="smokestacks", size=12),   # 10 rows + 2 border
        Layout(name="hourly"),                 # remaining terminal space
    )
    layout["top_row"].split_row(
        Layout(name="quota",      ratio=3),
        Layout(name="efficiency", ratio=2),
    )

    layout["header"].update(
        Text(
            f"  YAH MULE v{__version__} — Claude Efficiency Monitor       {ts}",
            style="bold cyan",
        )
    )
    layout["quota"].update(panel_quota(d))
    layout["efficiency"].update(panel_efficiency(d))
    layout["pattern"].update(panel_pattern(d))
    layout["trend"].update(panel_trend(d))
    layout["smokestacks"].update(panel_smokestacks(d))
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

    # --profile: enable timing log
    global _profile_fh
    if "--profile" in sys.argv:
        _profile_fh = open(_profile_path, "a", encoding="utf-8")
        _profile_fh.write(f"\n--- profile session {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        _profile_fh.flush()
        mem_note = "" if _PSUTIL else " (install psutil for memory tracking)"
        print(f"[profile] logging to {_profile_path}{mem_note}", file=sys.stderr)

    # --interval  (default 300s — was 60s; use --interval 60 to restore old cadence)
    interval = 300
    if "--interval" in sys.argv:
        try:
            interval = int(sys.argv[sys.argv.index("--interval") + 1])
        except (IndexError, ValueError):
            pass

    # --once: single-shot, no live loop
    once = "--once" in sys.argv

    console = Console()

    if once:
        tok = _prof_start("fetch_all")
        d = fetch_all()
        _prof_end(tok)
        ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        console.print(build_layout(d, ts))
        return

    # Full-screen live mode
    tok = _prof_start("fetch_all (init)")
    d = fetch_all()
    _prof_end(tok)
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    last_fetch = time.monotonic()
    last_minute = datetime.now().minute

    with Live(
        build_layout(d, ts),
        screen=True,
        console=console,
        refresh_per_second=0.2,
    ) as live:
        data_dirty = False  # initial build already done above
        while True:
            time.sleep(5)
            now_mono = time.monotonic()
            now_dt   = datetime.now()
            ts       = now_dt.strftime("%Y-%m-%d  %H:%M:%S")

            # Fetch new data on interval
            if now_mono - last_fetch >= interval:
                tok = _prof_start("fetch_all")
                d = fetch_all()
                _prof_end(tok)
                last_fetch = now_mono
                data_dirty = True

            # Rebuild layout only when data changed OR the minute ticked
            # (minute tick drives hourglass animation + timestamp display)
            if data_dirty or now_dt.minute != last_minute:
                tok = _prof_start("build_layout")
                live.update(build_layout(d, ts))
                _prof_end(tok)
                last_minute = now_dt.minute
                data_dirty = False


if __name__ == "__main__":
    main()
