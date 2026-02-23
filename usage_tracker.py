"""
Claude Efficiency Tracker
Pulls daily cost data from ccusage JSON (authoritative source), writes to SQLite + OUTBOX.
Runs: 2:30 AM daily via Task Scheduler. Zero Claude quota cost.

Data source: ccusage (npm global at C:/Users/ghigh/AppData/Roaming/npm/ccusage.cmd)
Uses shell=True to ensure ccusage.cmd is found on Windows.
"""

import json
import os
import subprocess
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path

# --- Config ---
CCUSAGE_CMD = "ccusage"   # Found via shell=True; full path fallback below if needed
DB_PATH = Path("G:/ai/_data/analytics.db")
OUTBOX_DIR = Path("G:/z.ai/workspace/BILLY_OUTBOX")
PLAN_MONTHLY_USD = 100.0
PLAN_DAILY_USD = PLAN_MONTHLY_USD / 30.0

WEEKLY_BUDGET_FLOOR = 0.45   # 45% manual reserve (protected)
SCHEDULED_RESERVE = 0.08     # 8% reserved for daily crons (daily-quotes, journal, Billy)
AUTO_SPRINT_CEILING = 0.47   # Remaining 47% for automated sprints
RATIO_FLOOR = 12.0           # Alert if efficiency drops below this
RATIO_BASELINE = 15.5        # Established Feb 7-21


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS efficiency_daily (
            date TEXT PRIMARY KEY,
            api_cost_usd REAL,
            plan_prorata_usd REAL,
            efficiency_ratio REAL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_write_tokens INTEGER,
            models_used TEXT,
            week_budget_pct REAL,
            recorded_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS automated_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT,
            sprint TEXT,
            task_name TEXT,
            task_type TEXT,
            status TEXT,
            tokens_used_estimate INTEGER,
            outcome_notes TEXT,
            recorded_at TEXT
        )
    """)
    conn.commit()
    return conn


def fetch_ccusage_data(since_days=8):
    """Pull daily cost data from ccusage JSON output.

    ccusage is the authoritative source — it handles deduplication correctly
    and uses live LiteLLM pricing. Using shell=True ensures ccusage.cmd is
    found on Windows without needing explicit PATH setup.

    Returns: dict mapping date string ("YYYY-MM-DD") to ccusage row dict.
    """
    since = (date.today() - timedelta(days=since_days)).strftime("%Y%m%d")
    try:
        result = subprocess.run(
            f"{CCUSAGE_CMD} daily --json --since {since}",
            capture_output=True, text=True, timeout=30, shell=True
        )
        data = json.loads(result.stdout)
        return {row["date"]: row for row in data.get("daily", [])}
    except Exception as e:
        print(f"[usage_tracker] ccusage call failed: {e}")
        return {}


def get_week_start():
    """Week resets Sunday. Return most recent Sunday."""
    today = date.today()
    days_since_sunday = today.weekday() + 1  # Mon=0, so Sun = -1 mod 7
    if days_since_sunday == 7:
        days_since_sunday = 0
    return today - timedelta(days=days_since_sunday)


def write_to_db(conn, ccusage_data, week_start):
    """Write ccusage daily rows to DB. ccusage is the authoritative cost source."""
    c = conn.cursor()
    now = datetime.now().isoformat()
    WEEKLY_API_BASELINE = 55.0
    rows = []

    for day, row in sorted(ccusage_data.items()):
        api_cost = row.get("totalCost", 0.0)
        plan_cost = PLAN_DAILY_USD
        ratio = api_cost / plan_cost if plan_cost > 0 else 0
        models = [mb.get("modelName", "") for mb in row.get("modelBreakdowns", [])]
        total_input = row.get("inputTokens", 0)
        total_output = row.get("outputTokens", 0)
        total_cache_read = row.get("cacheReadTokens", 0)
        total_cache_write = row.get("cacheCreationTokens", 0)

        c.execute("""
            INSERT OR REPLACE INTO efficiency_daily
            (date, api_cost_usd, plan_prorata_usd, efficiency_ratio,
             input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
             models_used, week_budget_pct, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            day, round(api_cost, 4), round(plan_cost, 4), round(ratio, 2),
            total_input, total_output, total_cache_read, total_cache_write,
            json.dumps(models), None, now
        ))
        rows.append((day, api_cost, ratio))

    # Update week_budget_pct for this week's rows
    week_str = week_start.strftime("%Y-%m-%d")
    week_cost = sum(r[1] for r in rows if r[0] >= week_str)
    week_pct = min(week_cost / WEEKLY_API_BASELINE, 1.0)
    c.execute(
        "UPDATE efficiency_daily SET week_budget_pct = ? WHERE date >= ?",
        (round(week_pct, 4), week_str)
    )

    conn.commit()
    return rows


def write_outbox_report(ccusage_data, week_start):
    if not OUTBOX_DIR.exists():
        return

    WEEKLY_API_BASELINE = 55.0
    today = date.today().strftime("%Y-%m-%d")
    today_row = ccusage_data.get(today, {})
    today_cost = today_row.get("totalCost", 0.0)
    today_ratio = today_cost / PLAN_DAILY_USD if today_cost > 0 else 0

    rolling_cost = sum(
        ccusage_data.get((date.today() - timedelta(days=i)).strftime("%Y-%m-%d"), {}).get("totalCost", 0.0)
        for i in range(7)
    )
    rolling_ratio = rolling_cost / (PLAN_DAILY_USD * 7)

    week_str = week_start.strftime("%Y-%m-%d")
    week_cost = sum(
        ccusage_data.get((week_start + timedelta(days=i)).strftime("%Y-%m-%d"), {}).get("totalCost", 0.0)
        for i in range(7)
    )
    week_pct = min(week_cost / WEEKLY_API_BASELINE * 100, 100)

    alerts = []
    if rolling_ratio < RATIO_FLOOR:
        alerts.append(f"WARNING: Efficiency ratio {rolling_ratio:.1f}x below floor ({RATIO_FLOOR}x)")
    if week_pct > AUTO_SPRINT_CEILING * 100:
        alerts.append(f"WARNING: Sprint budget >{AUTO_SPRINT_CEILING*100:.0f}% used ({week_pct:.0f}%) -- protect manual + scheduled reserve")
    if week_pct > 92:
        alerts.append(f"CRITICAL: Usage at {week_pct:.0f}% -- scheduled tasks at risk of quota failure")

    models_7d = {}
    for i in range(7):
        d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")
        for mb in ccusage_data.get(d, {}).get("modelBreakdowns", []):
            m = mb.get("modelName", "")
            models_7d[m] = models_7d.get(m, 0) + 1

    report = f"""# Usage Report — {today}

**Week budget**: {week_pct:.0f}% used (resets Sunday)
**Today**: ${today_cost:.2f} API-equivalent | efficiency {today_ratio:.1f}x
**7-day rolling**: ${rolling_cost:.2f} | efficiency {rolling_ratio:.1f}x
**Baseline**: {RATIO_BASELINE}x | Floor: {RATIO_FLOOR}x
**Data source**: ccusage (authoritative)

## Budget Allocation
- Manual reserve: 45% (protected)
- Scheduled tasks reserve: 8% (daily-quotes, journal, Billy -- do not consume)
- Auto sprints: 47% ceiling | {max(0, AUTO_SPRINT_CEILING*100 - week_pct):.0f}% remaining this week

## Alerts
{chr(10).join(alerts) if alerts else '✅ No alerts'}

## Models (7-day)
"""
    for m, days in sorted(models_7d.items(), key=lambda x: -x[1]):
        report += f"- {m}: {days} day(s)\n"

    out_path = OUTBOX_DIR / f"USAGE_REPORT_{today}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"Report written: {out_path}")


def main():
    print(f"[efficiency-tracker] Starting — {datetime.now().isoformat()}")

    conn = init_db()
    print("DB initialized")

    ccusage_data = fetch_ccusage_data(since_days=8)
    if not ccusage_data:
        print("[efficiency-tracker] WARNING: ccusage returned no data — DB not updated")
        conn.close()
        return
    print(f"Fetched {len(ccusage_data)} days of data from ccusage")

    week_start = get_week_start()
    rows = write_to_db(conn, ccusage_data, week_start)
    print(f"Wrote {len(rows)} rows to DB")

    write_outbox_report(ccusage_data, week_start)

    today = date.today().strftime("%Y-%m-%d")
    today_rows = [r for r in rows if r[0] == today]
    if today_rows:
        _, cost, ratio = today_rows[0]
        print(f"Today: ${cost:.2f} API-equiv | ratio {ratio:.1f}x (baseline {RATIO_BASELINE}x)")

    conn.close()
    print("[efficiency-tracker] Done")


if __name__ == "__main__":
    main()
