@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Run scripts\setup.bat first.
  exit /b 1
)

if not exist "%PROJECT_ROOT%\input\danbooru.env" (
  echo [ERROR] Danbooru credentials not configured.
  call "%~dp0setup_danbooru.bat"
  if errorlevel 1 exit /b 1
)

echo Collecting copyright tags into input\series.csv ...
"%VENV_PYTHON%" "%BACKEND_DIR%\tools\collect_series_tags.py" %*
exit /b %ERRORLEVEL%
