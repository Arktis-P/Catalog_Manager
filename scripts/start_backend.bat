@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Virtual environment not found. Run scripts\setup.bat first.
  exit /b 1
)

echo Starting backend on http://127.0.0.1:%BACKEND_PORT%
pushd "%BACKEND_DIR%"
"%VENV_PYTHON%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %BACKEND_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
