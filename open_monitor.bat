@echo off
REM Yah Mule -- live monitor launcher
REM Always launches yah_mule.py (unified entry point, version-independent).

wt -w 0 sp -p "Yah Mule" -H --size 0.35 -- python "%~dp0yah_mule.py"
