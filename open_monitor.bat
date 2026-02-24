@echo off
REM Yah Mule v2 -- live monitor launcher
REM Opens a WT split pane and runs kpi_display_v2.py directly.
REM v2 owns its own rich.live loop -- no watch.ps1 wrapper needed.

wt -w 0 sp -p "Yah Mule" -H --size 0.35 -- python "%~dp0kpi_display_v2.py"
