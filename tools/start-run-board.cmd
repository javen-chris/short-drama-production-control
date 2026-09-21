@echo off
chcp 65001 >nul
setlocal

rem ---------------------------------------------------------------
rem 实时运行总表启动器（通用版，路径全部相对，仓库挪到哪都能用）
rem   用法一：双击运行，然后把项目文件夹拖进黑窗口回车
rem   用法二：start-run-board.cmd "D:\某项目目录"
rem ---------------------------------------------------------------

rem 仓库根目录 = 本脚本所在目录(tools)的上一级
set "CONSOLE=%~dp0.."
for %%I in ("%CONSOLE%") do set "CONSOLE=%%~fI"

if not exist "%CONSOLE%\tools\render_run_report.py" (
  echo.
  echo   找不到 tools\render_run_report.py。
  echo   请把本脚本放在控制台仓库的 tools\ 目录下再运行。
  echo.
  pause
  exit /b 1
)

set "PROJ=%~1"
if not "%PROJ%"=="" goto run

echo.
echo   实时运行总表 —— 查看进度 / 录入段清单
echo   ============================================================
echo   把【项目文件夹】拖到本窗口后按回车；直接回车 = 看仓库自带示例。
echo.
set /p PROJ=
if not "%PROJ%"=="" goto run
set "PROJ=%CONSOLE%\examples\episode_demo"

:run
set "PROJ=%PROJ:"=%"
if not exist "%PROJ%\workflow\run_index.json" (
  echo.
  echo   该项目目录下还没有运行轨迹：
  echo     %PROJ%\workflow\run_index.json
  echo   确认拖进来的是项目文件夹，而不是 workflow 或 runs 子目录。
  echo.
  pause
  exit /b 1
)

echo.
echo   项目：%PROJ%
echo   服务地址：http://127.0.0.1:8765/   （浏览器会自动打开）
echo   若 8765 被占用会自动往后试，以窗口里实际打印的网址为准。
echo   关掉本窗口 = 停止服务。
echo.

set "PY=python"
where python >nul 2>nul && goto havepy
set "PY=py"
where py >nul 2>nul && goto havepy
echo.
echo   没有找到 Python（已试过 python 与 py）。
echo   请先安装 Python，或把本脚本里的 PY= 改成你的解释器绝对路径。
echo.
pause
exit /b 1

:havepy
"%PY%" "%CONSOLE%\tools\render_run_report.py" "%PROJ%" --serve

echo.
echo   服务已停止。按任意键关闭本窗口。
pause >nul
