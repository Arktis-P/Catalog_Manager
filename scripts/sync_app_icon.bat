@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo Virtual environment missing. Run scripts\setup.bat first.
  exit /b 1
)

echo Syncing app icon from appicon.png...
"%VENV_PYTHON%" "%PROJECT_ROOT%\scripts\generate_app_icon.py"
if errorlevel 1 exit /b 1

echo Building frontend so dist/ picks up the new favicon...
pushd "%FRONTEND_DIR%"
call npm run build
set "BUILD_EXIT=%ERRORLEVEL%"
popd
if %BUILD_EXIT% NEQ 0 exit /b %BUILD_EXIT%

echo.
echo App icon synced. Restart the app ^(scripts\launch_desktop.bat^).
exit /b 0
