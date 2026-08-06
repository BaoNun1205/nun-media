@echo off
cd /d "%~dp0"
start "Stitch API" cmd /k ""%~dp0run_backend.bat""
start "Stitch UI" cmd /k ""%~dp0run_frontend.bat""
echo Backend:  http://127.0.0.1:8008
echo Frontend: http://127.0.0.1:5173
