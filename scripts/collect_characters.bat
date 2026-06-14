@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo [ERROR] Run scripts\setup.bat first.
  exit /b 1
)

if not exist "%PROJECT_ROOT%\input\danbooru.env" (
  echo [ERROR] Configure Danbooru credentials first: scripts\setup_danbooru.bat
  exit /b 1
)

echo Collecting characters from Danbooru...
"%VENV_PYTHON%" "%BACKEND_DIR%\tools\collect_characters.py" %*
exit /b %ERRORLEVEL%
