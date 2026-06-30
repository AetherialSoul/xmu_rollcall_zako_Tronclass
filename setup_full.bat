@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "NO_PAUSE="
if /i "%~1"=="/nopause" set "NO_PAUSE=1"

echo Full setup will install the core toolkit plus optional auto-evaluation and course-selection integrations.
echo.

call "%~dp0setup.bat" /nopause
if errorlevel 1 goto :fail

call "%~dp0setup_optional_integrations.bat" /nopause
if errorlevel 1 goto :fail

echo.
echo Full setup complete.
echo Run run.bat, open Settings, and fill your XMU account before using auto login.
if not defined NO_PAUSE pause
exit /b 0

:fail
echo.
echo Full setup failed. Check the error above.
if not defined NO_PAUSE pause
exit /b 1
