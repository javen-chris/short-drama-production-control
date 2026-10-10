"""Process housekeeping for the run board: find it, free its port, fix the console.

This module used to be called `start_run_board.py` and carried its own launcher -
an interactive "which project?" menu that scanned directories and remembered the
last choice. That menu is gone: `tools/一键打开看板.cmd` is now the single way to
open the board, and it reads `tools/board-project.txt` instead.

What is left here is only what a launcher needs before it can start a server:
reclaim the port from a previous board, refuse to kill anything else, and make
Chinese render in the black window. The name says "process" rather than "start"
so nobody mistakes it for an entry point again - the confusion between a module
and a launcher is exactly how this repository ended up with five ways to start
one board.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

#: The port the board serves on. Kept here because both the reclaim below and the
#: launcher's readiness probe need to agree on it.
BOARD_PORT = 8765

#: Command-line markers that identify a *launcher* rather than the served process.
#: A launcher whose renderer was killed keeps its own console open, and if a
#: second launcher starts while the first is still alive the two take turns
#: killing each other's board - the user sees a page that loads and then dies.
#: There is one launcher now, so the marker list has one entry.
LAUNCHER_MARKERS = ("open_board.py",)


def free_the_port(port: int = BOARD_PORT) -> str:
    """Stop whatever old board is holding the port, so a restart always works.

    The board re-reads *data* from disk on every request, but Python loads its
    *code* once at start-up. So after the code changes, an old process keeps
    serving the old page and no amount of refreshing in the browser helps. The
    fix is a restart, and the user should never have to hunt a PID through a task
    manager: whoever holds the port is by definition a previous board.

    Only kills processes that look like a board (python + render_run_report),
    never a random listener that happens to share the port.
    """
    if os.name != "nt":
        return "非 Windows，跳过端口回收。"
    # A renderer can survive after its launcher or sit behind a runtime shim.
    # Reclaim every old renderer first; killing only the listener PID left an
    # old process tree alive and made a fresh browser page look stale.
    protected = _protected_processes()
    old_renderers = [pid for pid, command in python_processes().items()
                     if "render_run_report" in command and pid not in protected]
    for pid in old_renderers:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            pass
    if old_renderers:
        time.sleep(1.0)
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "无法查询端口占用（netstat 不可用），继续尝试启动。"

    pids: set[int] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            try:
                pids.add(int(parts[4]))
            except ValueError:
                continue
    if not pids:
        return ""

    stopped: list[str] = []
    skipped: list[str] = []
    for pid in pids:
        if not _looks_like_board(pid):
            skipped.append(str(pid))
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=15)
            stopped.append(str(pid))
        except (OSError, subprocess.SubprocessError):
            skipped.append(str(pid))

    if stopped:
        time.sleep(1.5)  # let Windows release the socket before we rebind
    if skipped:
        print(f"  注意：端口 {port} 上还有 {', '.join(skipped)} 号进程不是我启动的看板，"
              "没有动它。若启动失败，请关掉占用该端口的程序。")
    return f"已停止旧看板进程：{', '.join(stopped)}" if stopped else ""


def _command_line(pid: int) -> str:
    """The full command line of a process, or "" if it cannot be read.

    Uses .NET through PowerShell, not wmic: wmic was removed from Windows 11
    (verified absent on this machine, 2026-09-25), and a probe that silently
    returns "" would make the port reclaim below never fire - the failure mode
    being "restart appears to work and still serves the old page".
    """
    if os.name != "nt":
        return ""
    for shell in ("powershell.exe", "pwsh.exe"):
        try:
            out = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\")."
                 "CommandLine"],
                capture_output=True, text=True, timeout=20,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip().lower()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _looks_like_board(pid: int) -> bool:
    """Is this PID a previous run board? Refuse to kill anything else."""
    return "render_run_report" in _command_line(pid)


def python_processes() -> dict[int, str]:
    """Every running python.exe with its command line, in one shell call.

    One PowerShell round trip for the whole list, because asking per-PID (the way
    `_command_line` does) costs a shell start-up each time and this runs before
    every board launch.
    """
    if os.name != "nt":
        return {}
    for shell in ("powershell.exe", "pwsh.exe"):
        try:
            out = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                 "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
                capture_output=True, text=True, timeout=30,
            )
            if out.returncode != 0 or not out.stdout.strip():
                continue
            found: dict[int, str] = {}
            for line in out.stdout.splitlines():
                pid_text, _, command = line.partition("\t")
                try:
                    found[int(pid_text.strip())] = command.strip().lower()
                except ValueError:
                    continue
            return found
        except (OSError, subprocess.SubprocessError):
            continue
    return {}


def _parent_process_id(pid: int) -> int | None:
    """Return a process parent, when Windows exposes it.

    The launcher can itself be started through cmd.exe, a shortcut host, or a
    test runner.  A command-line substring is not enough to distinguish an old
    launcher from the process tree that is currently starting this launcher.
    """
    if os.name != "nt":
        return None
    for shell in ("powershell.exe", "pwsh.exe"):
        try:
            out = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").ParentProcessId"],
                capture_output=True, text=True, timeout=20,
            )
            if out.returncode == 0 and out.stdout.strip():
                return int(out.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None


def _protected_processes(start_pid: int | None = None) -> set[int]:
    """PIDs in the current process ancestry that must never be killed."""
    current = start_pid or os.getpid()
    protected: set[int] = set()
    while current and current not in protected:
        protected.add(current)
        current = _parent_process_id(current) or 0
    return protected


def _is_stale_launcher(pid: int, command: str, *, protected: set[int] | None = None) -> bool:
    """Whether a process is an old launcher, not the current launch chain."""
    if pid in (protected or _protected_processes()):
        return False
    return "open_board.py" in command.lower()


def stop_stale_launchers() -> str:
    """Kill other launcher processes so this launch is the only one.

    Double-clicking twice in a row can otherwise leave two launchers alive: the
    new board binds the port, and the older launcher - whose renderer was just
    killed - either takes the port back or is killed in turn by the next click.
    Killing the stale launcher first makes the most recent click authoritative,
    which is what a second double-click implies.
    """
    if os.name != "nt":
        return ""
    protected = _protected_processes()
    stopped: list[str] = []
    for pid, command in python_processes().items():
        if _is_stale_launcher(pid, command, protected=protected) and any(
                marker in command for marker in LAUNCHER_MARKERS):
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, text=True, timeout=15)
                stopped.append(str(pid))
            except (OSError, subprocess.SubprocessError):
                continue
    return f"已停止旧的启动器进程：{', '.join(stopped)}" if stopped else ""


def fix_windows_console() -> None:
    """Make Chinese render in the black window instead of mojibake.

    cmd.exe starts on code page 936 (GBK) while Python prints UTF-8, so every
    project name came out as garbage. Switching the console itself to 65001 and
    re-pointing stdout at UTF-8 fixes both display and input. Done from Python,
    never from the .cmd: a `chcp` line in a batch file shifts cmd's read pointer
    and tears the rest of the script apart.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
