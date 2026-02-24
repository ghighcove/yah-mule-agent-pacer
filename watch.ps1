# watch.ps1 -- Yah Mule -- Claude Efficiency Live Monitor
# Run in a WT pane: .\watch.ps1
# Or: powershell -ExecutionPolicy Bypass -File <path-to>\yah-mule-agent-pacer\watch.ps1
#
# yah_mule.py runs its own rich.live refresh loop — no PS wrapper needed.
# Pass --interval N to change refresh rate (default 60s). Ctrl+C to exit.

$PYTHON    = "python"   # Update to full path if needed
$LAUNCHER  = "$PSScriptRoot\yah_mule.py"
$INTERVAL  = 60

& $PYTHON $LAUNCHER --interval $INTERVAL
