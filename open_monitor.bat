@echo off
REM Claude Monitor — recovery launcher
REM Run this if the monitor pane isn't open or you need to restart it.
REM Opens in a new WT split pane alongside whatever is active.

wt -w 0 sp -p "Claude Monitor" -H --size 0.35
