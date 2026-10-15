@echo off
cd /d "%~dp0"
echo ========================================================
echo   Launching CareerPulse Web Dashboard...
echo   Open in browser: http://127.0.0.1:8000
echo ========================================================
python -m career_pulse.cli serve
pause
