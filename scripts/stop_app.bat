@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

echo Stopping Catalogue Manager processes...

for %%P in (%BACKEND_PORT% %FRONTEND_PORT%) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    taskkill /PID %%A /F >nul 2>&1
  )
)

echo Done. Ports %BACKEND_PORT% and %FRONTEND_PORT% should be free.
echo Logs remain in: %PROJECT_ROOT%\logs
exit /b 0
