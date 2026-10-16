@echo off
cd /d "c:\Users\KIIT\OneDrive\Documents\Automate Jobs\Job Scrapper"

start "CareerPulse" /min "C:\Users\KIIT\AppData\Local\Programs\Python\Python313\python.exe" -m uvicorn career_pulse.web.app:app --host 127.0.0.1 --port 8000 --reload --no-access-log
start "" "C:\Users\KIIT\AppData\Local\Programs\Python\Python313\pythonw.exe" "scripts\lid_monitor.py"
timeout /t 3 /nobreak >nul
start http://127.0.0.1:8000
