@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%FRONTEND_DIR%\node_modules" (
  echo [ERROR] Frontend dependencies not installed. Run scripts\setup.bat first.
  exit /b 1
)

echo Starting frontend on http://127.0.0.1:%FRONTEND_PORT%
pushd "%FRONTEND_DIR%"
call npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
