"""Pick a project and open its live run board.

Double-clicking tools\\start-run-board.cmd lands here. We scan a few known
roots for directories that carry workflow\\run_index.json, list them, and let
the user choose by number. Everything else asks for a path, which means nobody
has to drag a folder into a black window.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

CONSOLE = Path(__file__).resolve().parents[1]
TOOLS = CONSOLE / "tools"
ROOTS_FILE = TOOLS / "start-run-board.roots.txt"
STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "short-drama-board"
LAST_FILE = STATE_DIR / "last_project.txt"
MAX_DEPTH = 3
SKIP_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv"}


def read_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("RUN_BOARD_ROOTS", "")
    for part in env.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part))
    if ROOTS_FILE.is_file():
        # lstrip the BOM so the file survives a round trip through Notepad
        text = ROOTS_FILE.read_text(encoding="utf-8").lstrip("\ufeff")
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                roots.append(Path(line))
    return roots or [TOOLS.parent / "examples"]


def _subdirs(base: Path):
    if not base.is_dir():
        return
    yield base
    for depth in range(1, MAX_DEPTH + 1):
        pattern = "/".join(["*"] * depth)
        try:
            found = list(base.glob(pattern))
        except OSError:
            return
        for candidate in found:
            if not candidate.is_dir():
                continue
            if candidate.name in SKIP_NAMES:
                continue
            yield candidate


def _describe(project: Path) -> str:
    try:
        index = json.loads((project / "workflow" / "run_index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "（轨迹文件读不出来）"
    series = index.get("series") or index.get("project") or "未命名"
    episode = index.get("episode") or "-"
    runs = index.get("runs") or []
    return f"{series} {episode} · 共 {len(runs)} 段"


def find_projects(roots: list[Path]) -> list[Path]:
    seen: set[str] = set()
    found: list[Path] = []
    for root in roots:
        for candidate in _subdirs(root):
            if not (candidate / "workflow" / "run_index.json").is_file():
                continue
            key = str(candidate.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
    found.sort(key=lambda p: (p / "workflow" / "run_index.json").stat().st_mtime, reverse=True)
    return found


def load_last() -> Path | None:
    try:
        text = LAST_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    path = Path(text)
    return path if (path / "workflow" / "run_index.json").is_file() else None


def remember(project: Path) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_FILE.write_text(str(project), encoding="utf-8")
    except OSError:
        pass


def add_root(project: Path) -> None:
    """Remember the parent of a hand-typed project, so next time it shows up."""
    parent = project.parent
    try:
        existing = ROOTS_FILE.read_text(encoding="utf-8").splitlines() if ROOTS_FILE.is_file() else []
    except OSError:
        existing = []
    wanted = str(parent)
    if any(line.strip() == wanted for line in existing):
        return
    existing.append(wanted)
    try:
        ROOTS_FILE.write_text("\n".join(existing) + "\n", encoding="utf-8")
    except OSError:
        pass


def choose(project: Path) -> None:
    add_root(project)
    remember(project)
    print()
    print(f"正在打开：{project}")
    print("服务起来后浏览器会自动弹出；关掉这个黑窗口就会停止。")
    print()
    subprocess.call(
        [sys.executable, str(TOOLS / "render_run_report.py"), str(project), "--serve"]
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    wants_last = "--last" in args

    print()
    print("  实时运行总表 —— 查看进度 / 录入段清单")
    print("  ============================================================")
    projects = find_projects(read_roots())
    last = load_last()

    if wants_last and last is not None:
        choose(last)
        return 0

    if not projects:
        print("  在已知的目录里没有找到带运行轨迹的项目。")
    else:
        print("  找到这些项目，输入序号后回车：")
        print()
        for number, project in enumerate(projects, start=1):
            print(f"    {number}. {project.name}  [{_describe(project)}]")
            print(f"       {project}")

    print()
    if last:
        print(f"  直接回车 = 上次看的那个：{last.name}")
    print("  也可以把项目文件夹直接拖进来后回车（只取路径，不会复制文件）。")

    answer = input("  请选择：").strip().strip('"')
    if not answer:
        if last is None:
            print("  没有上次记录，请重新运行并选一个序号。")
            return 1
        choose(last)
        return 0

    if answer.isdigit():
        position = int(answer)
        if 1 <= position <= len(projects):
            choose(projects[position - 1])
            return 0
        print(f"  没有第 {position} 项。")
        return 1

    project = Path(answer)
    if not (project / "workflow" / "run_index.json").is_file():
        print(f"  这个目录下没有运行轨迹：{project}\\workflow\\run_index.json")
        return 1
    choose(project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
