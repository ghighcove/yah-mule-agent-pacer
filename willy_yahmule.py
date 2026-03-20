#!/usr/bin/env python3
"""
willy_yahmule.py — Remote agent capacity vs. workload dashboard.

Connects to a secondary compute node (Ollama worker) via SSH and displays:
  - Model roster + RAM usage
  - TD queue depth (open / done)
  - Idletime last-run age
  - COAL vs. STEAM dispatch-readiness ratio

Configuration — set via environment variables or a local config file:
  REMOTE_HOST      IP or hostname of the worker node
  REMOTE_USER      SSH username
  REMOTE_KEY_PATH  Path to SSH private key (preferred over password)
  REMOTE_PASSWORD  SSH password (fallback if no key configured)

  Or create willy_monitor_config.py in the same directory:
    REMOTE_HOST = "192.168.x.x"
    REMOTE_USER = "yourusername"
    REMOTE_KEY_PATH = "/path/to/key"  # optional

Usage:
    python willy_yahmule.py              # connect live, print once
    python willy_yahmule.py --watch 30   # refresh every 30 seconds
    python willy_yahmule.py --cached     # read last local snapshot
"""

from __future__ import annotations
import io, json, os, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_TOOLS = Path(__file__).parent
sys.path.insert(0, str(_TOOLS))

# ── ANSI ──────────────────────────────────────────────────────────────────────
R    = "\033[0m"
CY   = "\033[96m"
GR   = "\033[92m"
YL   = "\033[93m"
RD   = "\033[91m"
BL   = "\033[94m"
WH   = "\033[97m"
DM   = "\033[90m"
BOLD = "\033[1m"
_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

def _strip(s): return _ANSI_RE.sub("", s)
def _bar(pct, width=12, color=BL):
    filled = int(pct / 100 * width)
    return f"{color}{'█'*filled}{DM}{'░'*(width-filled)}{R}"
def _hline(c="━", w=88, col=CY): return f"{col}{c*w}{R}"
def _section(title):
    bar = f"{CY}── {title} "
    fill = 88 - len(_strip(bar)) - 3
    return bar + f"{DM}" + "─"*max(0, fill) + f"{R} ──"


# ── Config — env vars override local config file ───────────────────────────────
def _load_config() -> dict:
    cfg = {"host": None, "user": None, "key_path": None, "password": None,
           "queue_path": "~/agent/queue.md",
           "outbox_pattern": "~/agent/workspace/OUTBOX/IDLETIME_*.md",
           "inbox_path": "~/agent/workspace/INBOX/*.md",
           "busy_flag": "~/agent/.agent_busy",
           "cached_snapshot": None}

    # Try local config file first
    try:
        import importlib.util
        cfg_file = _TOOLS / "willy_monitor_config.py"
        if cfg_file.exists():
            spec = importlib.util.spec_from_file_location("_wm_cfg", cfg_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            cfg["host"]     = getattr(mod, "REMOTE_HOST",     None)
            cfg["user"]     = getattr(mod, "REMOTE_USER",     None)
            cfg["key_path"] = getattr(mod, "REMOTE_KEY_PATH", None)
            cfg["password"] = getattr(mod, "REMOTE_PASSWORD", None)
            cfg["queue_path"]      = getattr(mod, "QUEUE_PATH",      cfg["queue_path"])
            cfg["outbox_pattern"]  = getattr(mod, "OUTBOX_PATTERN",  cfg["outbox_pattern"])
            cfg["inbox_path"]      = getattr(mod, "INBOX_PATH",       cfg["inbox_path"])
            cfg["busy_flag"]       = getattr(mod, "BUSY_FLAG",        cfg["busy_flag"])
            cfg["cached_snapshot"] = getattr(mod, "CACHED_SNAPSHOT",  None)
    except Exception:
        pass

    # Env vars take precedence
    cfg["host"]     = os.environ.get("REMOTE_HOST",      cfg["host"])
    cfg["user"]     = os.environ.get("REMOTE_USER",      cfg["user"])
    cfg["key_path"] = os.environ.get("REMOTE_KEY_PATH",  cfg["key_path"])
    cfg["password"] = os.environ.get("REMOTE_PASSWORD",  cfg["password"])

    return cfg


# ── SSH data fetch ─────────────────────────────────────────────────────────────
def fetch_live() -> dict:
    try:
        import paramiko
    except ImportError:
        return {"error": "paramiko not installed — pip install paramiko"}

    cfg = _load_config()
    if not cfg["host"] or not cfg["user"]:
        return {"error": "REMOTE_HOST and REMOTE_USER not configured. "
                         "Set env vars or create willy_monitor_config.py"}

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = dict(hostname=cfg["host"], username=cfg["user"], timeout=8)
        if cfg["key_path"]:
            connect_kwargs["key_filename"] = cfg["key_path"]
        elif cfg["password"]:
            connect_kwargs["password"] = cfg["password"]

        ssh.connect(**connect_kwargs)

        def run(cmd):
            _, o, _ = ssh.exec_command(cmd)
            return o.read().decode("utf-8", errors="replace").strip()

        models_raw  = run("curl -s http://localhost:11434/api/tags")
        mem_raw     = run("python3 -c \"import psutil; m=psutil.virtual_memory(); "
                          "print(m.used//1024**3, m.total//1024**3)\"")
        load_raw    = run("uptime | awk -F'load averages:' '{print $2}'")
        queue_open  = run(f"grep -c '- \\[ \\]' {cfg['queue_path']} 2>/dev/null || echo 0")
        queue_done  = run(f"grep -c '- \\[x\\]' {cfg['queue_path']} 2>/dev/null || echo 0")
        busy_flag   = run(f"test -f {cfg['busy_flag']} && echo YES || echo NO")
        last_idle   = run(f"ls -t {cfg['outbox_pattern']} 2>/dev/null | head -1 | "
                          "xargs basename 2>/dev/null || echo none")
        inbox_count = run(f"ls {cfg['inbox_path']} 2>/dev/null | wc -l | tr -d ' '")

        ssh.close()

        models = []
        try:
            mdata = json.loads(models_raw)
            for m in mdata.get("models", []):
                models.append({
                    "name":     m.get("name", "?"),
                    "size_gb":  m.get("size", 0) / 1024**3,
                    "modified": m.get("modified_at", "")[:10],
                })
        except Exception:
            pass

        mem_parts = mem_raw.split()
        mem_used  = int(mem_parts[0]) if len(mem_parts) > 0 and mem_parts[0].isdigit() else 0
        mem_total = int(mem_parts[1]) if len(mem_parts) > 1 and mem_parts[1].isdigit() else 0

        return {
            "models":       models,
            "mem_used_gb":  mem_used,
            "mem_total_gb": mem_total,
            "load":         load_raw.strip(),
            "queue_open":   int(queue_open or 0),
            "queue_done":   int(queue_done or 0),
            "busy":         busy_flag == "YES",
            "last_idle_file": last_idle,
            "inbox_count":  int(inbox_count or 0),
            "fetched_at":   datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_cached() -> dict:
    cfg = _load_config()
    snapshot = cfg.get("cached_snapshot")
    if snapshot:
        path = Path(snapshot)
    else:
        # Fallback: look for heartbeat JSON adjacent to this script
        path = _TOOLS / "agent_heartbeat.json"

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            met  = data.get("metrics", {})
            return {
                "models":       [],
                "mem_used_gb":  met.get("mem_used_gb", 0),
                "mem_total_gb": met.get("mem_total_gb", 0),
                "load":         str(met.get("load_1m", "?")),
                "queue_open":   0,
                "queue_done":   0,
                "busy":         False,
                "last_idle_file": met.get("last_outbox_file", "?"),
                "inbox_count":  0,
                "fetched_at":   data.get("ts", "?"),
                "note":         "cached snapshot (no live SSH)",
            }
        except Exception:
            pass
    return {"error": "no cached snapshot found"}


# ── Render ─────────────────────────────────────────────────────────────────────
def render(data: dict) -> list[str]:
    if "error" in data:
        return [f"  {RD}Error: {data['error']}{R}"]

    ts = datetime.now().strftime("%a %d %b  %H:%M:%S")
    out = [
        _hline(),
        f"  {BOLD}{CY}AGENT YAH MULE{R}  {DM}{ts}   capacity vs. workload{R}",
        _hline(),
        "",
    ]

    # ── CAPACITY ──
    out.append(_section("CAPACITY"))

    mem_used  = data.get("mem_used_gb", 0)
    mem_total = data.get("mem_total_gb", 0) or 1
    mem_pct   = mem_used / mem_total * 100
    mem_col   = RD if mem_pct > 85 else YL if mem_pct > 65 else GR
    out.append(f"  RAM    {_bar(mem_pct, 14, mem_col)} {mem_used:.0f}/{mem_total:.0f}GB  ({mem_pct:.0f}%)")

    load = data.get("load", "?")
    out.append(f"  Load   {DM}{load}{R}")
    out.append("")

    models = data.get("models", [])
    if models:
        total_model_gb = sum(m["size_gb"] for m in models)
        out.append(f"  {DM}Ollama — {len(models)} models  {total_model_gb:.1f}GB loaded{R}")
        for m in sorted(models, key=lambda x: x["size_gb"], reverse=True)[:8]:
            bar = _bar(m["size_gb"] / max(total_model_gb, 1) * 100, 8, DM)
            out.append(f"    {WH}{m['name']:<32}{R} {bar} {m['size_gb']:.1f}GB  {DM}{m['modified']}{R}")
    else:
        out.append(f"  {DM}Model roster: SSH required (run live){R}")
    out.append("")

    # ── WORKLOAD ──
    out.append(_section("WORKLOAD"))

    busy      = data.get("busy", False)
    q_open    = data.get("queue_open", 0)
    q_done    = data.get("queue_done", 0)
    inbox     = data.get("inbox_count", 0)
    last_idle = data.get("last_idle_file", "none")

    busy_str = f"{RD}BUSY{R}" if busy else f"{GR}IDLE{R}"
    out.append(f"  Status   {busy_str}")

    q_color = RD if q_open > 10 else YL if q_open > 5 else GR
    out.append(f"  Queue    {q_color}{BOLD}{q_open}{R} open  {DM}{q_done} done{R}")

    if inbox > 0:
        out.append(f"  Inbox    {YL}{BOLD}{inbox}{R} items pending")
    else:
        out.append(f"  Inbox    {DM}0 pending{R}")

    last_idle_short = last_idle if last_idle != "none" else "—"
    out.append(f"  Last run {DM}{last_idle_short}{R}")
    out.append("")

    # ── COAL vs. STEAM ──
    out.append(_section("COAL vs. STEAM"))
    if q_open == 0:
        ratio_line = f"  {GR}Queue empty — agent ready for more work{R}"
    elif busy:
        ratio_line = f"  {YL}Burning: {q_open} items queued, job in progress{R}"
    elif q_open <= 3:
        ratio_line = f"  {GR}Light queue ({q_open} items) — good time to dispatch more{R}"
    elif q_open <= 8:
        ratio_line = f"  {YL}Moderate queue ({q_open} items) — hold new dispatches unless urgent{R}"
    else:
        ratio_line = f"  {RD}Heavy queue ({q_open} items) — let agent drain before adding more{R}"
    out.append(ratio_line)

    if data.get("note"):
        out.append(f"  {DM}Note: {data['note']}{R}")

    out.append("")
    out.append(_hline("─", col=DM))
    fetched = data.get("fetched_at", "?")[:16]
    out.append(f"{DM}  agent_yahmule  ·  data: {fetched}Z{R}")

    return out


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Remote Ollama agent capacity vs. workload monitor."
    )
    parser.add_argument("--once",   action="store_true", help="Print once and exit (default)")
    parser.add_argument("--cached", action="store_true", help="Read last local snapshot")
    parser.add_argument("--watch",  type=int, default=0, metavar="SECS",
                        help="Refresh every N seconds (e.g. --watch 30)")
    args = parser.parse_args()

    def render_once():
        data = fetch_cached() if args.cached else fetch_live()
        print()
        for line in render(data):
            print(line)
        print()

    if args.watch:
        while True:
            print("\033[2J\033[H", end="")
            render_once()
            time.sleep(args.watch)
    else:
        render_once()


if __name__ == "__main__":
    main()
