@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "NO_PAUSE="
if /i "%~1"=="/nopause" set "NO_PAUSE=1"
set "PY=.venv\Scripts\python.exe"
set "PIP=.venv\Scripts\pip.exe"

echo [1/5] Checking Python...
set "PYLAUNCH="
for %%V in (3.13 3.12 3.11 3) do (
  if not defined PYLAUNCH (
    py -%%V --version >nul 2>nul
    if not errorlevel 1 set "PYLAUNCH=py -%%V"
  )
)
if not defined PYLAUNCH (
  python --version >nul 2>nul
  if errorlevel 1 (
    echo Python 3.11+ is required. Please install Python from https://www.python.org/downloads/windows/
    if not defined NO_PAUSE pause
    exit /b 1
  )
  set "PYLAUNCH=python"
)

echo Using %PYLAUNCH%

echo [2/5] Creating virtual environment...
if not exist "%PY%" (
  %PYLAUNCH% -m venv .venv
  if errorlevel 1 goto :fail
)

echo [3/5] Installing Python dependencies...
"%PY%" "%~dp0tools\pip_retry.py" -U pip
if errorlevel 1 goto :fail
"%PY%" "%~dp0tools\pip_retry.py" -r requirements.txt
if errorlevel 1 goto :fail

echo [4/5] Installing Playwright browser...
"%PY%" -m playwright install chromium
if errorlevel 1 goto :fail

echo [5/5] Preparing local account config...
if not exist "account.local.json" (
  copy "account.example.json" "account.local.json" >nul
  echo Created account.local.json. Please fill your XMU username and password before using auto login.
)

echo.
echo Core setup complete.
echo Run run.bat to start the toolkit.
echo Run setup_optional_integrations.bat if you need auto evaluation and course selection.
if not defined NO_PAUSE pause
exit /b 0

:fail
echo.
echo Setup failed. Check the error above.
if not defined NO_PAUSE pause
exit /b 1
