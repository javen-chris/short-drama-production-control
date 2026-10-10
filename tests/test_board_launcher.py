"""One board, one way to start it.

This repository had five launch entries at one point - two `.cmd` files inside
`tools/`, two more outside the repo, and an interactive "which project?" menu -
spread across three different code paths and two ways of choosing a project.
They disagreed with each other, and because each one reclaims the port before
starting, double-clicking two of them in a row could leave a board that loaded
and then silently died.

The tests here hold the merged state in place: a single command file, pure ASCII
(the cmd.exe code-page trap), and no reference anywhere to a launcher that is not
on disk. They are cheap, and they are the difference between "we merged it once"
and "it stays merged".
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from tools import board_process

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

#: The one command file a user double-clicks. Everything else is an alias for it
#: or a plain command-line invocation.
THE_LAUNCHER = "一键打开看板.cmd"

#: Scripts that used to exist and must never quietly come back.
RETIRED = (
    "start-run-board.cmd",
    "start_run_board.py",
    "start-run-board.roots.txt",
    "start-run-board.roots.example.txt",
)


def _cmd_files() -> list[Path]:
    return sorted(p for p in TOOLS.glob("*.cmd") if p.is_file())


def test_there_is_exactly_one_launcher():
    found = [p.name for p in _cmd_files()]
    assert found == [THE_LAUNCHER], (
        f"expected exactly one launch entry ({THE_LAUNCHER}), found {found}. "
        "A second entry means two code paths that can disagree, and a second "
        "double-click that can kill the board the first one started."
    )


def test_the_launcher_calls_the_single_implementation():
    text = (TOOLS / THE_LAUNCHER).read_text(encoding="utf-8", errors="replace")
    assert "open_board.py" in text, f"{THE_LAUNCHER} must call open_board.py"


@pytest.mark.parametrize("name", [p.name for p in _cmd_files()] or [THE_LAUNCHER])
def test_every_launcher_is_pure_ascii(name):
    """cmd.exe reads batch files in the OEM code page, so Chinese in a .cmd tears."""
    path = TOOLS / name
    if not path.is_file():
        pytest.skip(f"{name} not present")
    data = path.read_bytes()
    offenders = [(i, b) for i, b in enumerate(data) if b > 127]
    assert not offenders, (
        f"{name} contains {len(offenders)} non-ASCII byte(s) at offset "
        f"{offenders[0][0]}; cmd.exe would mis-parse the rest of the file"
    )


def test_the_retired_launchers_are_gone():
    for name in RETIRED:
        assert not (TOOLS / name).exists(), (
            f"tools/{name} is back; the board has one entry point now"
        )


def test_the_entry_module_is_named_like_a_module_not_a_launcher():
    """`start_run_board.py` read as an entry point, which is how it got called as one."""
    assert (TOOLS / "board_process.py").is_file()
    assert not (TOOLS / "start_run_board.py").exists()


def test_nothing_references_a_launcher_that_is_not_on_disk():
    """A doc or a page that names a missing launcher sends the user to a dead file."""
    named = re.compile(r"[\w\u4e00-\u9fff-]*启动[\w\u4e00-\u9fff-]*\.cmd"
                       r"|start-run-board\.cmd|查看-[\w\u4e00-\u9fff-]*\.cmd")
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode("utf-8").split("\0")
    suspects = []
    for rel in tracked:
        path = Path(rel)
        is_source = path.suffix == ".py" and path.parts[0] in {"src", "tools"}
        is_documentation = path.suffix == ".md" and path.parts[0] in {"docs"}
        is_root_note = path.suffix == ".md" and len(path.parts) == 1
        if is_source or is_documentation or is_root_note:
            suspects.append(ROOT / path)

    missing: list[str] = []
    for path in suspects:
        if "retired-launchers" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in set(named.findall(text)):
            if not (TOOLS / name).is_file() and not (ROOT / name).is_file():
                missing.append(f"{path.relative_to(ROOT)} → {name}")
    assert not missing, "references to launchers that do not exist:\n  " + "\n  ".join(missing)


def test_current_launcher_process_tree_is_never_classified_as_stale():
    protected = {100, 101}
    assert not board_process._is_stale_launcher(
        101, "python tools/open_board.py", protected=protected
    )


def test_unrelated_python_process_is_not_a_stale_launcher():
    assert not board_process._is_stale_launcher(
        200, "python tools/render_run_report.py", protected={100}
    )
