# Willy Monitor — Remote Agent Fleet Dashboard

`willy_yahmule.py` extends yah-mule's Claude quota tracking into a second
dimension: watching a local AI worker node running [Ollama](https://ollama.com).

Where the main yah-mule tracks *how much of your AI budget you've spent*,
the Willy Monitor tracks *how much work your local model fleet can take on right now*.

---

## What It Does

Connects to a secondary compute node over SSH and displays a live COAL vs. STEAM
dashboard — a single-glance answer to: *is this machine ready for more work, or
should I let it drain first?*

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  WILLY YAH MULE  Thu 19 Mar  20:05:21   capacity vs. workload
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── CAPACITY ─────────────────────────────────────────────────────────────────── ──
  RAM    ░░░░░░░░░░░░░░ 0/24GB  (0%)
  Load   1.59 1.52 1.50

  Ollama — 11 models  40.9GB loaded
    qwen2.5:14b          █░░░░░░░ 8.4GB   2026-03-17
    llama3.2-vision:11b  █░░░░░░░ 7.3GB   2026-03-17
    ...

── WORKLOAD ─────────────────────────────────────────────────────────────────── ──
  Status   IDLE
  Queue    0 open  0 done
  Inbox    0 pending

── COAL vs. STEAM ───────────────────────────────────────────────────────────── ──
  Queue empty — agent ready for more work
```

---

## Setup

### 1. Install dependencies

```bash
pip install paramiko
```

### 2. Configure credentials

Copy the example config and fill in your node's details:

```bash
cp willy_monitor_config.example.py willy_monitor_config.py
# edit willy_monitor_config.py — never commit this file
```

Or set environment variables:

```bash
export REMOTE_HOST=192.168.x.x
export REMOTE_USER=yourusername
export REMOTE_KEY_PATH=~/.ssh/id_ed25519
```

### 3. Run

```bash
python willy_yahmule.py              # one-shot print
python willy_yahmule.py --watch 30   # refresh every 30 seconds
python willy_yahmule.py --cached     # read last local snapshot (no SSH)
```

---

## The Ollama Model Fleet — What's What

The worker node in this project runs [Ollama](https://ollama.com), a local
model server. Below is a plain-English guide to the model classes you're
likely to see in the roster.

Understanding these matters for dispatch decisions — sending the wrong model
a task wastes time, memory, and heat.

---

### Small / Fast Tier (1–3B parameters)

These load in under a second, use 1–2GB RAM, and respond in ~2–5 tokens/sec
on Apple Silicon. They're weak at reasoning but excellent at simple classification,
extraction, and summarization of short text.

**`phi3.5`** (2.2 GB) — Microsoft's 3.8B model, punches above its weight on
reasoning tasks for its size. Trained specifically to be useful on edge devices.
Good for: structured extraction, simple Q&A, format conversion, quick summaries.
Bad for: multi-step reasoning, long context, creative writing, anything requiring
world knowledge beyond its training cut. The "intern who follows instructions well."

**`llama3.2:3b`** (2.0 GB) — Meta's smallest production model. Fast, reliable,
broad general knowledge. Good for: triage, tagging, routing decisions, short
completions. Bad for: depth. Think of it as a capable autocomplete, not a reasoner.

**`qwen2.5:3b`** (1.9 GB) — Alibaba's 3B entry. Particularly strong at
structured output (JSON, tables) relative to its size — a useful trait when
your pipeline needs machine-readable responses. Good for: structured generation,
code snippets, quick classification. Bad for: nuanced judgment.

---

### Mid Tier (7–8B parameters)

The workhorses. These load in 3–5GB RAM and run at 8–15 tok/s on Apple
Silicon M4. They're the sweet spot for most autonomous agent tasks — fast
enough to run many in a session, capable enough for real reasoning.

**`qwen2.5:7b`** (4.7 GB) — The general-purpose workhorse. Alibaba's 7B
model is among the best at its weight class for instruction following,
multi-step tasks, and structured output. This is the default model for
most automated work. Good for: tech debt execution, summarization, code review,
report drafting, anything in an idletime queue. Bad for: tasks requiring
genuine synthesis across large bodies of knowledge — it will confabulate gaps.

**`qwen2.5-coder:7b`** (4.7 GB) — Same architecture as qwen2.5:7b but
fine-tuned on a code-heavy corpus. Noticeably better at Python, bash, and
structured file editing than the general model. Good for: code generation,
refactoring, test writing, reading stack traces. Bad for: prose, creative tasks,
or anything where the "coder" fine-tune gets in the way of natural language.
Route code tasks here explicitly.

**`deepseek-r1:7b`** (4.7 GB) — DeepSeek's reasoning model at 7B, using a
chain-of-thought architecture (the model "thinks" before answering, visible in
`<think>` tags). This is qualitatively different from other 7B models — it
works through problems step by step rather than pattern-matching to an answer.
Good for: debugging, logic problems, multi-step planning, anything where you'd
benefit from seeing the reasoning. Bad for: speed (thinking adds tokens),
tasks that don't benefit from deliberation (simple classification, fast
extraction). Think of it as the "slow but careful" option.

**`llama3.1:8b`** (4.9 GB) — Meta's 8B model. Extremely well-rounded, with
strong instruction following from extensive RLHF training. Good for: general
conversation, writing, summarization, instruction-heavy tasks. Bad for: code
specifics (qwen-coder beats it), reasoning depth (deepseek-r1 beats it).
The most "chat-like" model in the fleet.

---

### Vision Tier

Models that accept both text and images. Much heavier for their parameter
count — vision encoding is expensive.

**`llama3.2-vision:11b`** (7.8 GB) — Meta's multimodal model at 11B.
The quality vision model in the fleet. Good for: image description, document
OCR, reading screenshots, chart interpretation. Bad for: pure text tasks
(costs RAM that could serve a lighter model), anything requiring precision
math or code. Primary vision model — use this when quality matters.

**`moondream`** (1.7 GB) — A tiny specialist vision model designed for
speed. Impressively capable for its size. Good for: quick image classification,
simple caption generation, "is there a person in this image" style queries.
Bad for: detail-heavy analysis, multi-object scenes, long descriptions.
Use it when vision throughput matters more than depth.

---

### Large Tier (14B parameters — Willy's ceiling)

**`qwen2.5:14b`** (9.0 GB) — The top of what Willy can run comfortably.
At 14B parameters, this model can handle tasks that genuinely require reasoning
across a large context window, synthesizing multiple sources, or producing
publication-quality prose. Good for: wolfpack Pack Lead synthesis, complex
multi-step plans, writing that needs to sound like a person, cross-document
analysis. Bad for: anything time-sensitive (runs at ~5–8 tok/s on the M4),
and it's overkill for simple tasks. Treat this as the "senior consultant" —
bring it in for the hard problems, not the paperwork.

---

### Embedding Tier

**`nomic-embed-text`** (274 MB) — Not a generative model. Converts text into
high-dimensional vectors for semantic search, clustering, and similarity
matching. Tiny footprint, nearly instant. Good for: building searchable memory
stores, finding semantically similar documents, powering retrieval-augmented
generation (RAG). Bad for: generating text (it doesn't — it only encodes).
The infrastructure model that enables smarter retrieval in the rest of the stack.

---

### Model Routing Cheat Sheet

| Task type | Route to |
|-----------|----------|
| Quick classification / triage | `llama3.2:3b` or `qwen2.5:3b` |
| Structured JSON output | `qwen2.5:3b` or `qwen2.5:7b` |
| General autonomous task execution | `qwen2.5:7b` |
| Code generation / refactoring | `qwen2.5-coder:7b` |
| Multi-step reasoning / debugging | `deepseek-r1:7b` |
| General conversation / writing | `llama3.1:8b` |
| Quality vision tasks | `llama3.2-vision:11b` |
| Fast image classification | `moondream` |
| Synthesis / complex analysis | `qwen2.5:14b` |
| Semantic search / RAG | `nomic-embed-text` |
| 70B reasoning (Emperor only) | `qwen2.5:72b` / `deepseek-r1:70b` |

---

## What We're Building Toward

This dashboard is one instrument panel in a larger project: a local AI lab
running continuously on commodity Apple Silicon hardware, autonomous enough
to execute work overnight while the human sleeps, and visible enough to
understand at a glance in the morning.

The broader system routes work across multiple nodes — each with a different
model ceiling and a different role. The quota tracker in the main yah-mule
measures what goes to the cloud. This monitor measures what runs at home.
Together they give a complete picture of where AI compute is actually going.

The COAL vs. STEAM metaphor is intentional: the machine is a furnace. You
want to know whether to shovel more coal or let it burn through what's already
in there. Over-dispatching stalls jobs; under-dispatching wastes capacity.
The ratio is the signal.

---

## Configuration Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `REMOTE_HOST` | Worker node IP or hostname | (required) |
| `REMOTE_USER` | SSH username | (required) |
| `REMOTE_KEY_PATH` | SSH private key path | None (tries default) |
| `REMOTE_PASSWORD` | SSH password fallback | None |
| `QUEUE_PATH` | Path to task queue file on node | `~/agent/queue.md` |
| `OUTBOX_PATTERN` | Glob for outbox files | `~/agent/workspace/OUTBOX/IDLETIME_*.md` |
| `INBOX_PATH` | Glob for inbox files | `~/agent/workspace/INBOX/*.md` |
| `BUSY_FLAG` | Path to busy-lock file | `~/agent/.agent_busy` |
| `CACHED_SNAPSHOT` | Local path for `--cached` mode | auto-detect |

---

*Part of the [yah-mule-agent-pacer](https://github.com/ghighcove/yah-mule-agent-pacer) project.*
