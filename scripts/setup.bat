@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

echo ========================================
echo  Catalogue Manager - Setup
echo ========================================
echo Project: %PROJECT_ROOT%
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not installed or not on PATH.
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js/npm is not installed or not on PATH.
  exit /b 1
)

if not exist "%VENV_DIR%" (
  echo [1/4] Creating virtual environment: %VENV_DIR%
  python -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b 1
) else (
  echo [1/4] Virtual environment already exists.
)

echo [2/4] Installing Python dependencies...
"%VENV_PIP%" install --upgrade pip
"%VENV_PIP%" install -r "%REQUIREMENTS%"
if errorlevel 1 exit /b 1

echo [3/4] Installing frontend dependencies...
pushd "%FRONTEND_DIR%"
call npm install
if errorlevel 1 (
  popd
  exit /b 1
)
popd

echo [4/4] Writing Python lock file...
"%VENV_PIP%" freeze > "%PROJECT_ROOT%\requirements.lock"

echo.
echo Setup complete.
echo   Python venv : %VENV_DIR%
echo   Backend deps: %REQUIREMENTS%
echo   Frontend    : %FRONTEND_DIR%
echo.
echo Next: run scripts\launch_app.bat
exit /b 0
