@echo off
setlocal EnableExtensions
call "%~dp0_common.bat"

if not exist "%VENV_PYTHON%" (
  echo Virtual environment missing. Running setup...
  call "%~dp0setup.bat"
  if errorlevel 1 exit /b 1
)

if not exist "%PROJECT_ROOT%\input\network.env" (
  echo input\network.env is missing.
  echo Copy input\network.env.example to input\network.env, fill the upstream proxy settings,
  echo and set CATALOGUE_APP_PROXY_ENABLED=1.
  exit /b 2
)

pushd "%PROJECT_ROOT%"
"%VENV_PYTHON%" -m desktop.proxy_probe
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
