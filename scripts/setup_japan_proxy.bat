@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

set "NETWORK_ENV=%PROJECT_ROOT%\input\network.env"
set "NETWORK_EXAMPLE=%PROJECT_ROOT%\input\network.env.example"

if not exist "%NETWORK_ENV%" (
  copy /Y "%NETWORK_EXAMPLE%" "%NETWORK_ENV%" >nul
  if errorlevel 1 exit /b 1
  echo Created input\network.env from the Japan proxy template.
) else (
  echo input\network.env already exists; keeping the existing local file.
)

echo.
echo Fill these local-only values for your Japan SSH host:
echo   CATALOGUE_APP_PROXY_ENABLED=1
echo   CATALOGUE_PROXY_SSH_HOST=...
echo   CATALOGUE_PROXY_SSH_USER=...
echo   CATALOGUE_PROXY_SSH_KEY_FILE=...
echo.
echo The expected proxy country is already JP.
start "" notepad "%NETWORK_ENV%"
exit /b 0
