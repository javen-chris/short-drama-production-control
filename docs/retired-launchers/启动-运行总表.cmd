@echo off
setlocal

rem Run board launcher (menu). All logic lives in tools\start_run_board.py.
rem This file stays pure ASCII on purpose: cmd.exe shifts its read pointer per
rem character on UTF-8, so any Chinese byte in a .cmd tears later lines apart
rem ('not is not recognized' and friends). Same reason it never calls chcp.

set "CONSOLE="
for /d %%D in ("%~dp0*") do (
  if exist "%%D\tools\start_run_board.py" set "CONSOLE=%%D"
)
if not defined CONSOLE (
  if exist "%~dp0tools\start_run_board.py" set "CONSOLE=%~dp0"
)
if not defined CONSOLE (
  echo.
  echo   Cannot find the console repo next to this launcher.
  echo   Expected a nearby folder containing tools\start_run_board.py
  echo.
  pause
  exit /b 1
)

set "PY="
where python >nul 2>nul && set "PY=python"
if defined PY goto run
where py >nul 2>nul && set "PY=py"
if defined PY goto run
if exist "%USERPROFILE%\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" set "PY=%USERPROFILE%\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if defined PY goto run

echo.
echo   Python not found. Install Python, or edit the PY= line in this file.
echo.
pause
exit /b 1

:run
"%PY%" "%CONSOLE%\tools\start_run_board.py"

echo.
echo   Service stopped. Press any key to close.
pause >nul
