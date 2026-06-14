@echo off
setlocal EnableExtensions

set "APP_URL=%~1"
if "%APP_URL%"=="" set "APP_URL=http://127.0.0.1:5173"

rem Prefer dedicated app window (no browser tabs/toolbars)
where msedge >nul 2>&1
if not errorlevel 1 (
  start "" msedge --app=%APP_URL% --new-window
  exit /b 0
)

where chrome >nul 2>&1
if not errorlevel 1 (
  start "" chrome --app=%APP_URL% --new-window
  exit /b 0
)

rem Fallback: default browser
start "" "%APP_URL%"
exit /b 0
