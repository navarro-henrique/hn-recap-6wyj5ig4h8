@echo off
cd /d "%~dp0"
venv\Scripts\python.exe sync_garmin.py --days 3 >> garmin_sync.log 2>&1
venv\Scripts\python.exe generate_dashboard.py >> garmin_sync.log 2>&1
venv\Scripts\python.exe send_dashboard_email.py >> garmin_sync.log 2>&1
