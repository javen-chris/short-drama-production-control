"""Tests for the silence alarm: distinguish "no work" from "work not reported".

The distinction is the whole point. Before this module the board collapsed both
into one word ("stale"), and the two demand opposite responses:

    nobody is working        -> do nothing, silence is correct
    working, not reporting   -> stop everything, the trajectory is lying

These tests pin the distinction, including the trap that made it invisible: the
trajectory files themselves must never count as evidence of activity, or the
alarm silences itself.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from production_control import silence_alarm as sa


def _touch(path: Path, age_minutes: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    stamp = time.time() - age_minutes * 60
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "EP99"
    (root / "workflow" / "runs").mkdir(parents=True)
    return root


def test_a_moving_project_with_a_silent_trajectory_is_an_alarm(project: Path):
    """The 2026-09-25 case: files being produced, no trajectory written."""
    _touch(project / "workflow" / "TASK_CURRENT.md", age_minutes=16)
    old = time.time() - 979 * 60
    _touch(project / "workflow" / "runs" / "RUN-EP99-A1.json", age_minutes=979)

    verdict = sa.detect(project, newest_event_at=_iso(old), index_updated_at=_iso(old))

    assert verdict["alarm"] is True
    assert verdict["level"] == sa.NOT_REPORTING
    assert "未上报轨迹" in verdict["label"]
    assert verdict["artifact"]["relative"].endswith("TASK_CURRENT.md")


def test_trajectory_files_never_count_as_production_activity(project: Path):
    """Otherwise a freshly written run file would silence the alarm it needs."""
    (project / "workflow" / "runs").mkdir(parents=True, exist_ok=True)
    _touch(project / "workflow" / "runs" / "RUN-EP99-A1.json", age_minutes=1)
    _touch(project / "workflow" / "run_index.json", age_minutes=1)
    old = time.time() - 900 * 60

    verdict = sa.detect(project, newest_event_at=_iso(old), index_updated_at=_iso(old))

    assert verdict["alarm"] is False
    assert verdict["artifact"] == {}


def test_production_files_are_found_even_below_workflow(project: Path):
    _touch(project / "故事本&首尾帧" / "first_frame_v2.png", age_minutes=10)
    old = time.time() - 500 * 60

    verdict = sa.detect(project, newest_event_at=_iso(old), index_updated_at=_iso(old))

    assert verdict["alarm"] is True
    assert "first_frame_v2.png" in verdict["artifact"]["relative"]


def test_a_stopped_project_is_not_an_alarm(project: Path):
    """Both quiet -> normal end of work, not a broken channel."""
    _touch(project / "workflow" / "TASK_CURRENT.md", age_minutes=300)
    old = time.time() - 300 * 60

    verdict = sa.detect(project, newest_event_at=_iso(old), index_updated_at=_iso(old))

    assert verdict["alarm"] is False
    assert verdict["level"] == sa.QUIET_AFTER_WORK


def test_an_empty_project_is_not_an_alarm(project: Path):
    verdict = sa.detect(project, newest_event_at="", index_updated_at="")

    assert verdict["alarm"] is False
    assert verdict["level"] == sa.NEVER_STARTED


def test_healthy_when_both_are_moving(project: Path):
    _touch(project / "workflow" / "TASK_CURRENT.md", age_minutes=5)
    recent = time.time() - 5 * 60

    verdict = sa.detect(project, newest_event_at=_iso(recent), index_updated_at=_iso(recent))

    assert verdict["alarm"] is False
    assert verdict["level"] == sa.HEALTHY


def test_a_missing_project_directory_is_not_an_error(tmp_path: Path):
    verdict = sa.detect(tmp_path / "nope", newest_event_at="", index_updated_at="")

    assert verdict["alarm"] is False


def test_no_project_root_is_handled():
    verdict = sa.detect(None, newest_event_at="", index_updated_at="")

    assert verdict["alarm"] is False
    assert verdict["hint"]


def test_banner_only_renders_for_a_real_alarm():
    assert sa.banner_html({"alarm": False}) == ""
    assert sa.banner_html({}) == ""

    html = sa.banner_html({
        "alarm": True,
        "label": "疑似在执行但未上报轨迹",
        "detail": "最新产出文件写于 16 分钟前。",
        "hint": "让生产窗口补回报。",
        "artifact": {"relative": "workflow/TASK_CURRENT.md", "age_minutes": 16},
    })

    assert "疑似在执行但未上报轨迹" in html
    assert "TASK_CURRENT.md" in html
    assert 'role="alert"' in html


def _iso(timestamp: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
