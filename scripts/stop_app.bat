@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

echo Stopping Catalogue Manager processes...

for %%P in (%BACKEND_PORT% %FRONTEND_PORT%) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr /R /C:":%%P .*LISTENING"') do (
    taskkill /PID %%A /F >nul 2>&1
  )
)

echo Cleaning Catalogue Manager browser profile processes...
if exist "%VENV_PYTHON%" (
  "%VENV_PYTHON%" "%~dp0cleanup_browser_profile.py"
) else (
  powershell -NoProfile -Command ^
    "$needle = Join-Path $env:LOCALAPPDATA 'CatalogueManager\browser-profile';" ^
    "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe' OR Name = 'msedge.exe'\" |" ^
    "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) } |" ^
    "ForEach-Object { taskkill /F /T /PID $_.ProcessId >$null 2>&1 }"
)

echo Done. Ports %BACKEND_PORT% and %FRONTEND_PORT% should be free.
echo Logs remain in: %LOCALAPPDATA%\CatalogueManager\logs
exit /b 0
