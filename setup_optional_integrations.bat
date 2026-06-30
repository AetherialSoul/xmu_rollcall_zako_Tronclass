@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "INTEGRATIONS=%ROOT%integrations"
set "IQA_DIR=%INTEGRATIONS%\iqa_helper"
set "COURSE_DIR=%INTEGRATIONS%\course_helper"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "PIP=%ROOT%.venv\Scripts\pip.exe"

if not exist "%PY%" (
  echo Core virtual environment not found. Running setup.bat first...
  call "%ROOT%setup.bat"
  if errorlevel 1 exit /b 1
)

if not exist "%INTEGRATIONS%" mkdir "%INTEGRATIONS%"

echo [1/6] Checking git...
git --version >nul 2>nul
if errorlevel 1 (
  echo Git is required to install optional integrations. Please install Git for Windows first.
  pause
  exit /b 1
)

echo [2/6] Installing automatic evaluation helper...
if exist "%IQA_DIR%\.git" (
  git -C "%IQA_DIR%" pull --ff-only
) else (
  if exist "%IQA_DIR%" (
    echo %IQA_DIR% exists but is not a git checkout. Keeping it unchanged.
  ) else (
    git clone --depth 1 https://github.com/vintcessun/XMUIQAHelper "%IQA_DIR%"
  )
)
if errorlevel 1 goto :fail

echo [3/6] Writing automatic evaluation integration launcher...
if exist "%IQA_DIR%" (
  copy "%ROOT%tools\iqa_start_integrated.py" "%IQA_DIR%\start_integrated.py" >nul
  > "%IQA_DIR%\start.bat" echo @echo off
  >> "%IQA_DIR%\start.bat" echo cd /d "%%~dp0"
  >> "%IQA_DIR%\start.bat" echo if exist "..\..\.venv\Scripts\python.exe" ^(
  >> "%IQA_DIR%\start.bat" echo   "..\..\.venv\Scripts\python.exe" start_integrated.py
  >> "%IQA_DIR%\start.bat" echo ^) else ^(
  >> "%IQA_DIR%\start.bat" echo   python start_integrated.py
  >> "%IQA_DIR%\start.bat" echo ^)
  >> "%IQA_DIR%\start.bat" echo pause
)

echo [4/6] Installing course selection helper...
if exist "%COURSE_DIR%\.git" (
  git -C "%COURSE_DIR%" pull --ff-only
) else (
  if exist "%COURSE_DIR%" (
    echo %COURSE_DIR% exists but is not a git checkout. Keeping it unchanged.
  ) else (
    git clone --depth 1 https://github.com/wegret/XMUCourseHelper "%COURSE_DIR%"
  )
)
if errorlevel 1 goto :fail

echo [5/6] Preparing course selection config template...
if exist "%COURSE_DIR%" (
  if not exist "%COURSE_DIR%\config" mkdir "%COURSE_DIR%\config"
  if not exist "%COURSE_DIR%\config\user.example.yaml" copy "%ROOT%tools\course_user.example.yaml" "%COURSE_DIR%\config\user.example.yaml" >nul
  if not exist "%COURSE_DIR%\config\user.yaml" copy "%COURSE_DIR%\config\user.example.yaml" "%COURSE_DIR%\config\user.yaml" >nul
)

echo [6/6] Installing optional dependencies into the main venv...
if exist "%IQA_DIR%\pyproject.toml" "%PIP%" install playwright
if exist "%COURSE_DIR%\requirements.txt" "%PIP%" install -r "%COURSE_DIR%\requirements.txt"
if errorlevel 1 goto :fail
"%PY%" -m playwright install chromium
if errorlevel 1 goto :fail

echo.
echo Optional integrations installed.
echo Open the toolkit with run.bat, then use the Auto Evaluation and Course Selection buttons.
echo You can adjust account, captcha and interval settings in the toolkit Settings page.
pause
exit /b 0

:fail
echo.
echo Optional integration setup failed. Check network access to GitHub and the error above.
pause
exit /b 1
