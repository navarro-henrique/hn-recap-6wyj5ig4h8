@echo off
cd /d "%~dp0"
venv\Scripts\python.exe sync_garmin.py --days 3 >> garmin_sync.log 2>&1
venv\Scripts\python.exe generate_dashboard.py >> garmin_sync.log 2>&1
copy /y dashboard.html docs\index.html >> garmin_sync.log 2>&1
git add docs\index.html >> garmin_sync.log 2>&1
git commit -m "Daily dashboard update" >> garmin_sync.log 2>&1
git push >> garmin_sync.log 2>&1
