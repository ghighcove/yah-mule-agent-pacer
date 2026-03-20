# willy_monitor_config.example.py
# Copy this to willy_monitor_config.py and fill in your values.
# willy_monitor_config.py is gitignored — never commit credentials.

REMOTE_HOST = "192.168.x.x"          # LAN IP or hostname of your Ollama worker
REMOTE_USER = "yourusername"          # SSH username on the worker

# Authentication — use one:
REMOTE_KEY_PATH = "~/.ssh/id_ed25519" # Path to SSH private key (preferred)
# REMOTE_PASSWORD = "yourpassword"    # Fallback password auth (less secure)

# Paths on the remote machine (defaults work for standard willy layout)
QUEUE_PATH     = "~/agent/queue.md"
OUTBOX_PATTERN = "~/agent/workspace/OUTBOX/IDLETIME_*.md"
INBOX_PATH     = "~/agent/workspace/INBOX/*.md"
BUSY_FLAG      = "~/agent/.agent_busy"

# Local cached snapshot path (for --cached mode)
# CACHED_SNAPSHOT = "D:/Downloads/Agent/agent_heartbeat.json"
