# watch.ps1 -- Yah Mule -- Claude Efficiency Live Monitor
# Run in a WT pane: .\watch.ps1
# Or: powershell -ExecutionPolicy Bypass -File <path-to>\yah-mule-agent-pacer\watch.ps1

$PYTHON     = "python"   # Update to full path if needed (e.g., "C:\Python311\python.exe")
$KPI_SCRIPT = "$PSScriptRoot\kpi_display.py"
$REFRESH    = 60

while ($true) {
    Clear-Host

    $ts = Get-Date -Format "yyyy-MM-dd  HH:mm:ss"
    Write-Host ""
    Write-Host "  YAH MULE -- Claude Efficiency Monitor       $ts" -ForegroundColor Cyan
    Write-Host "  ============================================================" -ForegroundColor Cyan
    Write-Host ""

    & $PYTHON $KPI_SCRIPT
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [kpi_display.py failed - check Python path]" -ForegroundColor Red
    }

    Write-Host ""
    $msg = "  Refreshing in " + $REFRESH + "s  |  Ctrl+C to exit"
    Write-Host $msg -ForegroundColor DarkGray
    Write-Host ""

    Start-Sleep -Seconds $REFRESH
}
