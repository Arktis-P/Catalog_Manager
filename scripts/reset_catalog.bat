@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Run scripts\setup.bat first.
  exit /b 1
)

echo Stopping running app processes...
call "%~dp0stop_app.bat"

echo.
echo Resetting catalogue DB (series.csv reload, characters cleared)...
"%VENV_PYTHON%" "%BACKEND_DIR%\tools\reset_catalog.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%
