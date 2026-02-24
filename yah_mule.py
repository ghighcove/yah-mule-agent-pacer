"""
yah_mule.py — Yah Mule unified entry point.

Always run this file, regardless of internal version.
The underlying display module may change; this launcher stays the same.

Usage:
    python yah_mule.py              # live mode, 60s refresh
    python yah_mule.py --interval 30
    python yah_mule.py --once       # single-shot and exit
    python yah_mule.py --calibrate N [--sonnet-pct M]
"""

import kpi_display_v2 as _display

if __name__ == "__main__":
    _display.main()
