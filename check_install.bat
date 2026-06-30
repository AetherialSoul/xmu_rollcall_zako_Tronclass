@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "NO_PAUSE="
if /i "%~1"=="/nopause" set "NO_PAUSE=1"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found. Run setup_full.bat first.
  if not defined NO_PAUSE pause
  exit /b 1
)

".venv\Scripts\python.exe" "%~dp0tools\verify_install.py" --full
set "RESULT=%ERRORLEVEL%"
echo.
if "%RESULT%"=="0" (
  echo Install check passed.
) else (
  echo Install check failed. Review the messages above.
)
if not defined NO_PAUSE pause
exit /b %RESULT%
