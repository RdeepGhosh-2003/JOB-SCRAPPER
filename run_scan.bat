@echo off
cd /d "%~dp0"
echo ========================================================
echo   Running CareerPulse Job Portal Scan...
echo ========================================================
python -m career_pulse.cli scan
pause
