@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Running setup.bat first...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" "%~dp0zako_app_V2.0.py"
