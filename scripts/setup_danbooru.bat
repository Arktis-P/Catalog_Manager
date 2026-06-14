@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Run scripts\setup.bat first.
  exit /b 1
)

set "ENV_FILE=%PROJECT_ROOT%\input\danbooru.env"
set "ENV_EXAMPLE=%PROJECT_ROOT%\input\danbooru.env.example"

if not exist "%ENV_FILE%" (
  echo Creating %ENV_FILE% from example...
  copy /Y "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
  echo.
  echo Edit input\danbooru.env and set your Danbooru username + api_key.
  echo API key page: https://danbooru.donmai.us/profile
  echo.
  notepad "%ENV_FILE%"
)

echo Verifying Danbooru credentials...
"%VENV_PYTHON%" "%BACKEND_DIR%\tools\collect_series_tags.py" --verify-only
exit /b %ERRORLEVEL%
