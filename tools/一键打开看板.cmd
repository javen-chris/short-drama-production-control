@echo off
rem ============================================================
rem  ONE-CLICK BOARD LAUNCHER
rem  Double-click this file. It stops any previous board, starts
rem  a fresh one, and opens your browser.
rem  Keep the black window open - closing it stops the board.
rem
rem  Project directory is read from tools\board-project.txt
rem  (edit that file, not this one, to switch projects).
rem
rem  This file is deliberately pure ASCII: cmd.exe reads batch
rem  files in the OEM code page (936/GBK here), so Chinese in a
rem  .cmd becomes mojibake and can break parsing. All Chinese
rem  output comes from Python.
rem ============================================================
setlocal

set "CONSOLE=%~dp0.."
for %%I in ("%CONSOLE%") do set "CONSOLE=%%~fI"

set "PY="
if exist "%USERPROFILE%\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" set "PY=%USERPROFILE%\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (where py >nul 2>nul && set "PY=py")

if not defined PY (
  echo.
  echo   [X] Python not found. Install Python and try again.
  echo.
  pause
  exit /b 1
)

"%PY%" "%CONSOLE%\tools\open_board.py"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo.
  echo   Board exited with code %RC%. Press any key to close.
  pause >nul
)
