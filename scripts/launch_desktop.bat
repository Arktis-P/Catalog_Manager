@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo Virtual environment missing. Running setup...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)

if not exist "%FRONTEND_DIR%\node_modules" (
  echo Frontend dependencies missing. Running setup...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)

echo Starting Catalogue Manager desktop app...
"%VENV_PYTHON%" "%PROJECT_ROOT%\desktop\launcher.py"
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%
