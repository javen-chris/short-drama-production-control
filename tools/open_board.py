"""Open the run board for one project: stop the old one, start a fresh one.

Called by the double-clickable `tools\\一键打开看板.cmd`. All Chinese lives here
rather than in the batch file, because cmd.exe reads .cmd files in the OEM code
page (936/GBK on this machine) and turns UTF-8 Chinese into mojibake.

Why a restart is needed at all: the board re-reads *data* from disk on every
request, but Python loads its *code* once at start-up. After the code changes, an
old process keeps serving the old page forever, and no amount of refreshing in
the browser helps. Restarting is the fix, and the user should never have to find
a PID by hand.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

from board_process import (  # noqa: E402
    free_the_port,
    fix_windows_console,
    stop_stale_launchers,
)

PORT = 8765

#: How many ports forward to look before giving up. The server walks forward on
#: its own when the preferred port is taken, so the launcher must be willing to
#: find it there - otherwise it reports a URL nobody is listening on.
PORT_SPAN = 6

#: The server loads its code once at start-up, so a silently dead process means
#: the window looks "open" while the browser shows nothing. Restarting a few
#: times beats making the user diagnose it.
MAX_RESTARTS = 3

PROJECT_FILE = TOOLS / "board-project.txt"


def read_project() -> Path | None:
    """First non-comment line of tools\\board-project.txt.

    The project path is configured here rather than in the .cmd: the path is
    Chinese, and a .cmd holding UTF-8 Chinese breaks under cmd.exe's GBK code
    page. This file has no such constraint.
    """
    try:
        # lstrip the BOM so the file survives a round trip through Notepad
        text = PROJECT_FILE.read_text(encoding="utf-8").lstrip("\ufeff")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return Path(line)
    return None


def port_is_live(port: int) -> bool:
    """Is something answering on 127.0.0.1:port?"""
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(timeout: float = 20.0) -> int | None:
    """The first port in range that is actually serving, or None.

    The launcher must report the URL that works, not the URL it asked for. The
    server walks forward when its preferred port is taken, and a wrong URL in
    the window is indistinguishable from a broken board.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for candidate in range(PORT, PORT + PORT_SPAN):
            if port_is_live(candidate):
                return candidate
        time.sleep(0.3)
    return None


def run_once(project: Path) -> int:
    """Start the server, announce it, and block until it stops."""
    renderer = TOOLS / "render_run_report.py"
    # --no-open: the launcher opens the browser itself, once it has confirmed
    # which port the server settled on.
    proc = subprocess.Popen(
        [sys.executable, str(renderer), str(project),
         "--serve", "--port", str(PORT), "--no-open"]
    )
    try:
        live = wait_for_port()
        if live is None:
            print()
            print("  [!] 看板在 20 秒内没有起来。")
            print("      如果你刚改过代码，先看上面的报错信息；")
            print("      也可以把这段黑窗口的内容发出来。")
        else:
            url = f"http://127.0.0.1:{live}/"
            if live != PORT:
                print(f"  （{PORT} 被占用，看板已在 {live} 端口起来）")
            print()
            print(f"  >>> 看板地址：{url}")
            print("  >>> 浏览器马上会打开；如果没开，手动复制上面这一行。")
            print("  >>> 这个黑窗口不要关，关掉看板就停了。")
            print()
            try:
                webbrowser.open(url)
            except Exception:
                pass
        return proc.wait()
    except KeyboardInterrupt:
        print("\n  正在停止看板…")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.SubprocessError:
                proc.kill()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    fix_windows_console()

    print()
    print("  短剧生产线 · 实时运行总表")
    print("  " + "=" * 58)

    if args:
        project = Path(args[0])
    else:
        project = read_project()
        if project is None:
            print(f"  [X] 读不到项目配置：{PROJECT_FILE}")
            print("      请用记事本打开它，写上一行项目目录（# 开头是注释）。")
            return 1

    if not (project / "workflow").is_dir():
        print(f"  [X] 这个目录里没有 workflow\\ 子目录：{project}")
        print(f"      请用记事本打开 {PROJECT_FILE}，改成正确的项目目录。")
        return 1

    renderer = TOOLS / "render_run_report.py"
    if not renderer.is_file():
        print(f"  [X] 找不到看板程序：{renderer}")
        return 1

    print(f"  项目：{project}")
    # Launchers first, then the port: an old launcher would otherwise race this
    # one and can take the port back after the new board has bound it.
    stale = stop_stale_launchers()
    if stale:
        print(f"  {stale}")
    message = free_the_port(PORT)
    if message:
        print(f"  {message}")
    else:
        print("  端口空闲，直接启动。")

    for attempt in range(MAX_RESTARTS + 1):
        code = run_once(project)
        if code == 0:
            return 0
        if attempt < MAX_RESTARTS:
            print(f"  [!] 看板异常退出（代码 {code}），正在自动重启…第 {attempt + 1} 次")
            time.sleep(2)
        else:
            print(f"  [!] 看板连续退出，已放弃。最后退出代码：{code}")
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
