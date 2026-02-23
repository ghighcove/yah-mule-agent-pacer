# watch.ps1 -- Claude Efficiency Live Monitor (Tier 1)
# Run in a WT pane: .\watch.ps1
# Or: powershell -ExecutionPolicy Bypass -File G:\ai\automation\efficiency-tracker\watch.ps1

$PYTHON     = "E:\Python\Python38-32\python.exe"
$KPI_SCRIPT = "G:\ai\automation\efficiency-tracker\kpi_display.py"
$SINCE_DATE = "20260207"
$REFRESH    = 60

while ($true) {
    Clear-Host

    $ts = Get-Date -Format "yyyy-MM-dd  HH:mm:ss"
    Write-Host ""
    Write-Host "  CLAUDE EFFICIENCY MONITOR                 $ts" -ForegroundColor Cyan
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
