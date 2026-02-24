# Claude Efficiency Tracker — Build Spec
**Created**: 2026-02-21
**Build target**: Sunday 2026-02-22 (fresh quota week)
**Owner**: Glenn Highcove

---

## Purpose

Close the feedback loop between:
- Automated overnight task execution
- Token budget consumption
- Outcome quality
- Sprint scheduling adjustment

**North star KPI**: API-equivalent cost / pro-rata Max plan cost = **efficiency ratio**
- Current baseline: **~15.5x** (Feb 7–21: $774.38 API / $50 plan cost)
- Floor target: ≥12x (if it drops below this, something is wrong)
- Reach goal: sustain ≥15x while increasing automated task throughput

---

## Budget Policy

| Allocation | % | Notes |
|-----------|---|-------|
| Manual reserve | 45% | Protected. Admin, coding, planning, this kind of session |
| Automated sprints | 55% | Split across Sun/Wed/Fri overnight windows |
| Hard stop | Last 5% of week | Emergency only — protect Sunday reset |

Weekly quota resets: **Sunday** (confirmed Feb 21 observation)

Sprint schedule:
- **Sun 2AM–6AM**: Sprint 1 — heaviest automated work (~20%)
- **Wed 2AM–5AM**: Sprint 2 — mid-week refresh (~20%)
- **Fri 2AM–4AM**: Sprint 3 — light tasks only (~10%)
- **Sat**: Buffer only. No new automation.

---

## Components to Build

### 1. `usage_tracker.py`
**Location**: `usage_tracker.py` (repo root)
**Runs**: Daily 2:30AM via Task Scheduler (after Billy's 2AM dashboard)
**No Claude involvement** — pure Python, zero quota cost

What it does:
- Reads `~/.claude/projects/**/*.jsonl` directly (same source as ccusage)
- Extracts: date, model, input_tokens, output_tokens, cache_create_tokens, cache_read_tokens
- Computes per-day and rolling-7-day API-equivalent cost (using hardcoded rate table)
- Determines current week's budget % used
- Writes one row to `efficiency_daily` table in `usage_data.db` (local SQLite, auto-created)
- Optionally writes `USAGE_REPORT.md` to a configured output directory (set `OUTBOX_DIR` in `usage_tracker.py`)

Rate table (hardcoded, update if Anthropic changes pricing):
```python
RATES = {
    'claude-sonnet-4-6':  {'input': 3.00, 'output': 15.00, 'cache_write': 3.75, 'cache_read': 0.30},
    'claude-haiku-4-5':   {'input': 0.80, 'output': 4.00,  'cache_write': 1.00, 'cache_read': 0.08},
    'claude-opus-4-6':    {'input': 15.00,'output': 75.00, 'cache_write': 18.75,'cache_read': 1.50},
    'claude-sonnet-4-5':  {'input': 3.00, 'output': 15.00, 'cache_write': 3.75, 'cache_read': 0.30},
}
# Per million tokens. Divide actual token count by 1,000,000 before multiplying.
```

### 2. SQLite Schema Addition
**DB**: `usage_data.db` (local to repo, auto-created on first run, gitignored)

```sql
CREATE TABLE IF NOT EXISTS efficiency_daily (
    date TEXT PRIMARY KEY,          -- YYYY-MM-DD
    api_cost_usd REAL,              -- API-equivalent cost
    plan_prorata_usd REAL,          -- $100/30 * 1 = 3.33/day
    efficiency_ratio REAL,          -- api_cost / plan_prorata
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    models_used TEXT,               -- JSON array
    week_budget_pct REAL,           -- % of weekly quota used (estimated)
    recorded_at TEXT                -- ISO timestamp
);

CREATE TABLE IF NOT EXISTS automated_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT,                  -- YYYY-MM-DD
    sprint TEXT,                    -- 'sun_sprint1', 'wed_sprint2', 'fri_sprint3'
    task_name TEXT,
    task_type TEXT,                 -- 'content', 'code', 'data_collection', 'analysis'
    status TEXT,                    -- 'completed', 'partial', 'failed', 'skipped'
    tokens_used_estimate INTEGER,   -- read from JSONL delta before/after
    outcome_notes TEXT,
    recorded_at TEXT
);
```

### 3. Session Check Integration (optional)
**Addition**: Add one block at the top of your session check output:

```
━━━ EFFICIENCY STATUS ━━━
Week budget: XX% used (N days remaining until Sunday reset)
7-day efficiency ratio: XX.Xx  [baseline: 15.5x]
Last overnight run: YYYY-MM-DD HH:MM — N tasks, STATUS
━━━━━━━━━━━━━━━━━━━━━━━━
```

Reads from `analytics.db`. If DB doesn't exist yet, skips silently.

### 4. Dashboard Panel (optional)
**Addition**: New "Efficiency" panel in an HTML dashboard showing:
- 30-day efficiency ratio trend (sparkline or table)
- Current week: budget used % + days remaining
- Automated task completion rate (last 4 weeks)
- Alert if ratio drops below 12x

### 5. Billy OUTBOX Report Format
`USAGE_REPORT.md` written nightly:
```markdown
# Usage Report — YYYY-MM-DD

**Week budget**: XX% used (Xd remaining)
**Today**: $X.XX API-equivalent | efficiency Xx
**7-day rolling**: $XX.XX | efficiency XX.Xx
**Trend**: ↑/↓/→ vs prior 7 days

## Sprint Status
- Sun Sprint 1: XX% of 20% allocation used
- Wed Sprint 2: XX% of 20% allocation used
- Fri Sprint 3: not yet run

## Automated Tasks (last 24h)
- [task name]: completed / failed / skipped
```

### 6. Outcome Tracker Wiring
When any automated task runs, it logs via existing `outcome_tracker.py`:
```python
tracker.log_decision(
    decision_type='automated_task',
    action_taken='[task description]',
    rule_source='efficiency_tracker',
    metadata={'sprint': 'sun_sprint1', 'task_type': 'content', 'budget_pct_before': 12.0}
)
# After task completes:
tracker.record_outcome(
    decision_id=decision_id,
    outcome='success'|'partial'|'failure',
    evidence='[what was produced or what failed]',
    metadata={'tokens_used': N, 'budget_pct_after': 18.5}
)
```

---

## Task Scheduler Entries (to add Sunday)

| Task Name | Time | Script | Notes |
|-----------|------|--------|-------|
| `efficiency-tracker-daily` | 2:30 AM daily | `usage_tracker.py` | After Billy's 2AM dashboard |

---

## Sunday Build Order

1. `usage_tracker.py` — core engine, test against existing JSONL data
2. SQLite schema creation
3. Verify it produces correct ratio (target: ~15.5x for Feb 7–21 window)
4. `session_check.py` integration — add efficiency block
5. `generate_dashboard.py` panel
6. Task Scheduler entry
7. Billy OUTBOX report format
8. Outcome tracker wiring (last — needs tasks to wire to)

**Test**: Run manually, verify ratio matches ccusage output, verify report lands in OUTBOX.

---

## What Sunday 2AM Actually Runs

**Important**: Claude cannot self-initiate. Here's what IS automated at 2AM Sunday:
- Billy's journal (1AM) — GLM-4.7, no quota cost
- Billy's dashboard (2AM) — GLM-4.7, no quota cost
- `usage_tracker.py` (2:30AM) — pure Python, no quota cost ✅

**Sunday morning session** (when you open Claude Code):
- Quota is fresh
- Spec is in this file
- Build the tracker
- Then define Sprint 1 task categories together

The heavy automated Claude work (content generation, code tasks) starts **after** the tracker is built and we have defined task categories. Don't automate what we can't measure yet.

---

## Open Questions (resolve Sunday morning)

1. What are the Sprint 1 task categories? (content pipeline? idea triage? code tasks?)
2. How does headless Claude run? (Task Scheduler calling `claude` CLI? Billy intermediary?)
3. Profit/positive KPI thresholds for justifying $200 plan upgrade
