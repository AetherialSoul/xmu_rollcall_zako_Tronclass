@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "NO_PAUSE="
if /i "%~1"=="/nopause" set "NO_PAUSE=1"

set "ROOT=%~dp0"
set "INTEGRATIONS=%ROOT%integrations"
set "IQA_DIR=%INTEGRATIONS%\iqa_helper"
set "COURSE_DIR=%INTEGRATIONS%\course_helper"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "PIP=%ROOT%.venv\Scripts\pip.exe"
set "IQA_ZIP_URL=https://github.com/vintcessun/XMUIQAHelper/archive/refs/heads/master.zip"
set "COURSE_ZIP_URL=https://github.com/wegret/XMUCourseHelper/archive/refs/heads/dev.zip"

if not exist "%PY%" (
  echo Core virtual environment not found. Running setup.bat first...
  call "%ROOT%setup.bat" /nopause
  if errorlevel 1 exit /b 1
)

if not exist "%INTEGRATIONS%" mkdir "%INTEGRATIONS%"

echo [1/6] Checking git...
set "HAS_GIT=1"
git --version >nul 2>nul
if errorlevel 1 (
  set "HAS_GIT=0"
  echo Git was not found. ZIP download fallback will be used.
)

echo [2/6] Installing automatic evaluation helper...
if exist "%IQA_DIR%\.git" (
  if "%HAS_GIT%"=="1" (
    call :git_retry git -C "%IQA_DIR%" pull --ff-only
  ) else (
    echo Existing automatic evaluation helper is a git checkout, but git is unavailable. Keeping it unchanged.
  )
) else (
  if exist "%IQA_DIR%" (
    if exist "%IQA_DIR%\main.py" (
      echo %IQA_DIR% exists but is not a git checkout. Keeping it unchanged.
    ) else (
      call :install_optional_repo "automatic evaluation helper" "%IQA_DIR%" "https://github.com/vintcessun/XMUIQAHelper" "%IQA_ZIP_URL%"
    )
  ) else (
    call :install_optional_repo "automatic evaluation helper" "%IQA_DIR%" "https://github.com/vintcessun/XMUIQAHelper" "%IQA_ZIP_URL%"
  )
)
if errorlevel 1 goto :fail
if not exist "%IQA_DIR%\main.py" (
  echo Automatic evaluation helper is incomplete: missing %IQA_DIR%\main.py
  echo Delete or rename %IQA_DIR% and rerun this script.
  goto :fail
)

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
  if "%HAS_GIT%"=="1" (
    call :git_retry git -C "%COURSE_DIR%" pull --ff-only
  ) else (
    echo Existing course selection helper is a git checkout, but git is unavailable. Keeping it unchanged.
  )
) else (
  if exist "%COURSE_DIR%" (
    if exist "%COURSE_DIR%\client.py" (
      echo %COURSE_DIR% exists but is not a git checkout. Keeping it unchanged.
    ) else (
      call :install_optional_repo "course selection helper" "%COURSE_DIR%" "https://github.com/wegret/XMUCourseHelper" "%COURSE_ZIP_URL%"
    )
  ) else (
    call :install_optional_repo "course selection helper" "%COURSE_DIR%" "https://github.com/wegret/XMUCourseHelper" "%COURSE_ZIP_URL%"
  )
)
if errorlevel 1 goto :fail
if not exist "%COURSE_DIR%\client.py" (
  echo Course selection helper is incomplete: missing %COURSE_DIR%\client.py
  echo Delete or rename %COURSE_DIR% and rerun this script.
  goto :fail
)

echo [5/6] Preparing course selection config template...
if exist "%COURSE_DIR%" (
  if not exist "%COURSE_DIR%\config" mkdir "%COURSE_DIR%\config"
  if not exist "%COURSE_DIR%\config\user.example.yaml" copy "%ROOT%tools\course_user.example.yaml" "%COURSE_DIR%\config\user.example.yaml" >nul
  if not exist "%COURSE_DIR%\config\user.yaml" copy "%COURSE_DIR%\config\user.example.yaml" "%COURSE_DIR%\config\user.yaml" >nul
)

echo [6/6] Installing optional dependencies into the main venv...
if exist "%IQA_DIR%\requirements.txt" (
  "%PY%" "%ROOT%tools\pip_retry.py" -r "%IQA_DIR%\requirements.txt"
  if errorlevel 1 goto :fail
)
if exist "%IQA_DIR%\pyproject.toml" (
  "%PY%" "%ROOT%tools\install_pyproject_dependencies.py" "%IQA_DIR%\pyproject.toml"
  if errorlevel 1 goto :fail
)
if exist "%COURSE_DIR%\requirements.txt" (
  "%PY%" "%ROOT%tools\pip_retry.py" -r "%COURSE_DIR%\requirements.txt"
  if errorlevel 1 goto :fail
)
if exist "%COURSE_DIR%\pyproject.toml" (
  "%PY%" "%ROOT%tools\install_pyproject_dependencies.py" "%COURSE_DIR%\pyproject.toml"
  if errorlevel 1 goto :fail
)
"%PY%" -m playwright install chromium
if errorlevel 1 goto :fail

echo.
echo Optional integrations installed.
echo Open the toolkit with run.bat, then use the Auto Evaluation and Course Selection buttons.
echo You can adjust account, captcha and interval settings in the toolkit Settings page.
if not defined NO_PAUSE pause
exit /b 0

:install_optional_repo
set "FEATURE_NAME=%~1"
set "DEST_DIR=%~2"
set "GIT_URL=%~3"
set "ZIP_URL=%~4"
if exist "%DEST_DIR%" (
  call :backup_incomplete_dir "%DEST_DIR%"
  if errorlevel 1 exit /b 1
)
if "%HAS_GIT%"=="1" (
  call :git_retry git clone --depth 1 "%GIT_URL%" "%DEST_DIR%"
  if not errorlevel 1 exit /b 0
)
call :download_zip_fallback "%ZIP_URL%" "%DEST_DIR%"
exit /b %ERRORLEVEL%

:git_retry
set "GIT_ATTEMPT=1"
:git_retry_loop
%*
if not errorlevel 1 exit /b 0
if !GIT_ATTEMPT! GEQ 3 exit /b 1
set /a GIT_ATTEMPT+=1
echo Git command failed. Retrying attempt !GIT_ATTEMPT!/3...
timeout /t 3 /nobreak >nul
goto :git_retry_loop

:backup_incomplete_dir
set "TARGET_DIR=%~1"
set "BACKUP_DIR=%TARGET_DIR%.incomplete_%RANDOM%%RANDOM%"
echo %TARGET_DIR% exists but is incomplete. Moving it to %BACKUP_DIR%
move "%TARGET_DIR%" "%BACKUP_DIR%" >nul
exit /b %ERRORLEVEL%

:download_zip_fallback
set "ZIP_URL=%~1"
set "DEST_DIR=%~2"
set "ZIP_FILE=%TEMP%\xmu_optional_%RANDOM%%RANDOM%.zip"
set "EXTRACT_DIR=%TEMP%\xmu_optional_extract_%RANDOM%%RANDOM%"
echo Git clone failed. Trying ZIP download fallback: %ZIP_URL%
if exist "%DEST_DIR%" (
  call :backup_incomplete_dir "%DEST_DIR%"
  if errorlevel 1 exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_FILE%' -UseBasicParsing"
if errorlevel 1 exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%ZIP_FILE%' -DestinationPath '%EXTRACT_DIR%' -Force"
if errorlevel 1 exit /b 1
for /d %%D in ("%EXTRACT_DIR%\*") do (
  move "%%D" "%DEST_DIR%" >nul
  if errorlevel 1 exit /b 1
  goto :zip_done
)
:zip_done
del "%ZIP_FILE%" >nul 2>nul
rmdir /s /q "%EXTRACT_DIR%" >nul 2>nul
exit /b 0

:fail
echo.
echo Optional integration setup failed. Check network access to GitHub and the error above.
if not defined NO_PAUSE pause
exit /b 1
