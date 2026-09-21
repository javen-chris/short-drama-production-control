@echo off
setlocal

rem Run board launcher. All logic lives in Python (tools\start_run_board.py);
rem keeping this file pure ASCII avoids the cmd.exe codepage parsing trap.

set "CONSOLE=%~dp0.."
for %%I in ("%CONSOLE%") do set "CONSOLE=%%~fI"

if not exist "%CONSOLE%\tools\start_run_board.py" (
  echo.
  echo   Missing tools\start_run_board.py
  echo   Put this script back in the tools directory of the console repo.
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
