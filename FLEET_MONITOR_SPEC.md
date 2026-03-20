# Fleet Monitor TUI — Design Spec
*Derived from wolfpack research session yahmule_tui (2026-03-19)*

## What This Is

A btop-style live terminal dashboard for monitoring a fleet of local AI agent
nodes. Evolves `willy_yahmule.py` from a clear-screen loop into a proper
panel-based TUI with distinct zones, async data refresh, and a clear path to
multi-node views when Emperor arrives.

**This is not cockpit.py.** cockpit.py is strategic — project health, stagnation
alerts, THIS WEEK planning. This monitor is operational — right now, is the
machine ready, what's burning, what's in the queue. Different cadence, different
audience (the engineer checking between dispatches, not the morning debrief).

---

## Library Decision: Rich Live + Layout

**Chosen over Textual.** Wolfpack pack lead recommended Textual; this spec
overrides that on practical grounds:

| Factor | Textual | Rich Live + Layout |
|--------|---------|-------------------|
| Already in stack | Yes (cockpit.py) | Yes (Rich) |
| Startup latency | High (event loop init) | Low (~100ms) |
| Win10 Python 3.8 32-bit | Works, edge cases | Works cleanly |
| SSH-over-WT | Terminal resize issues | No issues |
| Async polling | Built-in | Manual threading (simple) |
| Implementation complexity | High | Low-medium |
| Appropriate for this scope | Overkill | Right-sized |

Textual is the right choice for cockpit.py (complex, interactive, event-driven).
Rich Live is the right choice for yah_mule (display loop, no interaction needed,
fast startup, existing Rich dependency already covers it).

---

## Refresh Architecture

Three tiers — data freshness vs. SSH cost:

| Tier | Interval | What | Method |
|------|----------|------|--------|
| Fast | 2s | Busy flag, RAM %, load | SSH single command, batched |
| Medium | 15s | Queue depth, model roster, inbox count | SSH multi-command |
| Slow | 60s | OUTBOX file counts, last-run age | SSH ls + grep |

**Concurrency**: `threading.Thread` per node, `queue.Queue` for result hand-off
to the render loop. One thread per node × one thread per refresh tier = 2 threads
per node (fast+medium share, slow is its own). No asyncio required — Rich Live's
render loop is synchronous; threads feed it data.

**Failure handling**: If SSH times out (>5s), mark node as `UNREACHABLE` in red.
Last known data shown with a `[stale Xs]` suffix on the timestamp. Never crash
the display — degrade gracefully.

---

## NodeStatus Schema

```python
@dataclass
class NodeStatus:
    name: str                    # "Willy", "Emperor", "Win10"
    host: str                    # hostname or IP
    reachable: bool
    last_updated: datetime

    # Fast tier
    mem_used_gb: float
    mem_total_gb: float
    load_1m: float
    busy: bool

    # Medium tier
    queue_open: int
    queue_done: int
    inbox_count: int
    models: list[ModelInfo]      # see below

    # Slow tier
    outbox_recent: int           # files in last 24h
    last_idle_file: str          # basename of most recent OUTBOX file

@dataclass
class ModelInfo:
    name: str
    size_gb: float
    modified: str                # YYYY-MM-DD
    label: str                   # short capability tag (see MODEL_TAGS)
    active: bool                 # True if currently loaded in Ollama context
```

---

## MODEL_TAGS — Capability Labels

Shown conditionally when terminal width ≥ 110. Labels are 18 chars max.

```python
MODEL_TAGS = {
    "phi3.5":               "quick tasks",
    "llama3.2:3b":          "triage/routing",
    "qwen2.5:3b":           "structured output",
    "qwen2.5:7b":           "general workhorse",
    "qwen2.5-coder:7b":     "code/refactor",
    "deepseek-r1:7b":       "reasoning/debug",
    "llama3.1:8b":          "writing/chat",
    "llama3.2-vision:11b":  "vision (quality)",
    "moondream":            "vision (fast)",
    "qwen2.5:14b":          "synthesis/analysis",
    "nomic-embed-text":     "embeddings/RAG",
    # Emperor models (Phase 2)
    "qwen2.5:72b":          "orchestration 70B",
    "deepseek-r1:70b":      "chain-of-thought",
    "llama3.3:70b":         "general 70B",
}
```

Model row rendering:
```
# Width ≥ 110 (labels shown):
qwen2.5:14b       synthesis/analysis  █░░░░░░░ 8.4GB  2026-03-17

# Width < 110 (labels hidden):
qwen2.5:14b                           █░░░░░░░ 8.4GB  2026-03-17
```

---

## Color Scheme — btop DNA (MANDATORY)

The visual language must feel like btop. Not inspired by btop — actually btop. Anyone who uses btop
should open this and feel at home immediately.

### Palette

| Role | Color | Rich name | Use |
|------|-------|-----------|-----|
| Primary accent | Cyan `#00d7d7` | `bright_cyan` | Section headers, borders, title bar |
| Healthy / idle | Green `#87d700` | `bright_green` | IDLE status, low queue, RAM OK |
| Warning | Yellow `#ffaf00` | `bright_yellow` | Moderate load, mid queue depth |
| Critical / busy | Red `#ff5f5f` | `bright_red` | BUSY, high RAM, heavy queue |
| Active model | Blue `#5fafff` | `bright_blue` | Currently loaded/hot model highlight |
| Dim metadata | Grey `#626262` | `bright_black` / `dim` | Timestamps, secondary labels |
| Foreground | White `#e4e4e4` | `white` | Model names, TD IDs, values |
| Background | Terminal default | — | No forced background; respect terminal theme |

### btop Indicators to Carry Over

- **Progress bars**: `█` fill + `░` empty, colored by threshold (green→yellow→red).
  RAM bar goes green < 50%, yellow 50–75%, red > 75%. Load bar same.
- **Status pill**: `[IDLE]` in green, `[BUSY]` in red — right-aligned in node card header,
  same style as btop's CPU/MEM labels.
- **Section borders**: `┌─ SECTION NAME ───────────────────────────────────────────────┐`
  cyan border, white section name — exactly btop panel style.
- **Sparkline / trend** (Phase 2): if history available, show a 8-char ASCII sparkline for
  load (e.g. `▁▂▃▄▃▂▁▂`) using `▁▂▃▄▅▆▇█` chars. Low priority but high visual payoff.
- **Alert flash**: when RAM > 90% or queue > 30, the relevant value blinks (Rich `blink`).
  Use sparingly — only the number itself, not the whole line.
- **Model bar color**: size bar uses `bright_blue` for the largest model (the "hot" one
  likely loaded in context), `dim` blue for the rest.
- **Timestamp dim**: all timestamps, paths, and secondary labels in `dim` — never compete
  with the live values.

### What btop Does That We Must NOT Skip

- Color changes at thresholds are **instantaneous** — no gradual fade. Value crosses 75%,
  bar switches yellow. Crosses 90%, switches red. Same frame.
- Values that are zero or empty show as `—` (dim) not `0` — cleaner reading.
- Section headers are **always visible** even when panel content is truncated.
- The footer/statusline matches btop's bottom bar: dim, single line, navigation hints.

---

## Panel Layout

```
# Colors noted as [cyan] [green] [yellow] [red] [blue] [dim] [white]

[cyan]┌─────────────────────────────────────────────────────────────────────────────┐[/]
│  [white bold]FLEET MONITOR[/]  [dim]Thu 19 Mar  20:41[/]  ·  [white]1 node[/]  ·  [white]11 models[/]  ·  [white]0 jobs[/]       │
[cyan]└─────────────────────────────────────────────────────────────────────────────┘[/]

[cyan]┌── WILLY  Mac Mini M4 · 24GB ──────────────────────────── [[green]IDLE[/]] ──┐[/]
│  RAM   [green]░░░░░░░░░░░░░░[/]  [white]0/24GB (0%)[/]   Load  [dim]1.59 1.52 1.50[/]        │
│  Queue  [green bold]61[/] open  ·  [dim]23 done today[/]   Inbox  [dim]0[/]              │
│  Next   [white]TD-84[/]  [dim][content-strategy][/]  X.com bookmarks sync…          │
│  Last   [dim]TD-96  2026-03-19[/]                                        │
[cyan]└──────────────────────────────────────────────────────────────────────┘[/]

# BUSY state example — node card header:
[cyan]┌── WILLY ──────────────────────────────────────────────── [[red]BUSY[/]] ──┐[/]
│  RAM   [yellow]████████░░░░░░[/]  [yellow]14/24GB (58%)[/]   Load  [yellow]8.21 6.44 4.10[/]    │
│  [dim]Running[/]  [white]TD-86[/]  [dim][content-strategy][/]  [dim]·[/]  [dim]qwen2.5:14b[/]  [dim]· 4m12s[/]     │

[cyan]┌── MODELS ──────────────────────────────────────────────────────────────┐[/]
│  [blue bold]qwen2.5:14b[/]      [dim]synthesis/analysis[/]  [blue]████[/][dim]░░░░[/]  [white]8.4GB[/]  [dim]2026-03-17[/]  │
│  [white]llama3.2-vision[/]  [dim]vision (quality)[/]    [blue]███[/][dim]░░░░░[/]  [white]7.3GB[/]  [dim]2026-03-17[/]  │
│  [white]llama3.1:8b[/]      [dim]writing/chat[/]        [dim]██░░░░░░[/]  [white]4.9GB[/]  [dim]2026-03-16[/]  │
│  [white]qwen2.5-coder:7b[/] [dim]code/refactor[/]       [dim]██░░░░░░[/]  [white]4.7GB[/]  [dim]2026-03-19[/]  │
│  [white]qwen2.5:7b[/]       [dim]general workhorse[/]   [dim]██░░░░░░[/]  [white]4.7GB[/]  [dim]2026-03-16[/]  │
│  [white]deepseek-r1:7b[/]   [dim]reasoning/debug[/]     [dim]██░░░░░░[/]  [white]4.7GB[/]  [dim]2026-03-17[/]  │
│  [white]phi3.5[/]           [dim]quick tasks[/]         [dim]█░░░░░░░[/]  [white]2.2GB[/]  [dim]2026-03-16[/]  │
│  [white]llama3.2:3b[/]      [dim]triage/routing[/]      [dim]█░░░░░░░[/]  [white]2.0GB[/]  [dim]2026-03-16[/]  │
│  [dim]+3 more: qwen2.5:3b, moondream, nomic-embed-text[/]                 │
[cyan]└────────────────────────────────────────────────────────────────────────┘[/]

[cyan]┌── COAL vs. STEAM ──────────────────────────────────────────────────────┐[/]
│  [green]●[/] [white]WILLY[/]   [green]Queue empty — ready for more coal[/]                    │
│  # or if heavy: [red]●[/] [white]WILLY[/]   [red]Heavy (61) — let Willy drain[/]              │
[cyan]└────────────────────────────────────────────────────────────────────────┘[/]

[cyan]┌── ACTIVITY ────────────────────────────────────────────────────────────┐[/]
│  [dim]20:32[/]  [white]Willy[/]  TD-243 completed [dim](git commit discipline)[/]            │
│  [dim]19:15[/]  [white]Willy[/]  idletime batch — [green]3 TDs processed[/]                  │
[cyan]└────────────────────────────────────────────────────────────────────────┘[/]
  [dim]willy_yahmule  ·  fast: 2s  medium: 15s  slow: 60s  ·  q to quit[/]
```

**Active model highlight rule**: The largest model (most likely in Ollama context) gets
`bright_blue` bar. All others get `dim`. If Ollama `/api/ps` returns a running model,
that specific model gets `bright_blue` regardless of size.

**Panel priority** (what to show first when space is tight):
1. Node card (busy/idle + RAM — the single most important signal)
2. COAL vs. STEAM ratio
3. Queue depth + inbox
4. Model roster (below the fold if terminal is short)
5. Activity log (lowest priority — hide first)

---

## Phase Roadmap

### Phase 1 — MVP (build now)
- Single node: Willy only
- Rich Live render loop, 30s refresh (simple, no threading yet)
- Panels: node card, model roster with labels, COAL vs STEAM
- Conditional label render at width ≥ 110
- `--watch N` flag (existing), `--cached` fallback
- Replaces current clear-screen loop in `willy_yahmule.py`

### Phase 2 — Dual node (after Emperor arrives ~Apr 7)
- Add Emperor to `NodeStatus` pool
- Side-by-side node cards: Willy (left) · Emperor (right)
- Emperor models shown with 70B-specific labels
- Threading for concurrent SSH to both nodes
- Separate refresh timers per node (Emperor may be slower to respond early)

### Phase 3 — All-four unified (post-migration stable)
- Win10 status strip: Claude quota (from yah_mule main), Billy cron health
- Willy + Emperor node cards
- Inter-node message flow: CLAUDE_INBOX → Willy → Emperor → OUTBOX
- Activity log pulling from all nodes' OUTBOX directories
- New WT profile "Fleet Monitor" replacing separate Willy Monitor tab

---

## What Changes in willy_yahmule.py

| Area | Current | After |
|------|---------|-------|
| Render | `print()` loop with clear-screen | Rich `Live` context with `Layout` |
| Refresh | `time.sleep(N)` blocking | Threaded data fetch, render tick |
| Model rows | name + bar + size + date | + conditional label column |
| Error state | Prints error string | Red node card with `[UNREACHABLE]` |
| Multi-node | N/A | Phase 2 layout engine |
| Terminal width | Ignored | Drives label conditional |

---

## Files

| File | Purpose |
|------|---------|
| `willy_yahmule.py` | Main entry point (evolves in place) |
| `willy_monitor_config.py` | Local credentials (gitignored) |
| `willy_monitor_config.example.py` | Template |
| `FLEET_MONITOR_SPEC.md` | This file |
| `WILLY_MONITOR.md` | User-facing model guide + setup |

---

*Wolfpack research session: `wolfpack_yahmule_tui` · 2026-03-19 · 4 workers · qwen2.5:14b*
*Pack lead confidence: high · Library override: Rich Live (vs Textual recommended)*
