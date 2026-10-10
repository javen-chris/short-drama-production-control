"""Detect a project that is working but not reporting — the dangerous silence.

The board's worst failure mode is not a crash. It is a green, quiet page that
looks like "nothing to do" while a production window is busy writing files. On
2026-09-25 that is exactly what happened: the Feishu agent produced ten real
files for EP-EXAMPLE/A1, yet the trajectory file had not been touched in ~16 hours,
so the board showed stale progress and there was no way to tell

    "nobody is working"        (fine, silence is expected)
from
    "somebody is working, and the trajectory channel is not being written"
    (broken, and every downstream gate reads a lie)

`reporting_state()` in run_report only looks at the trajectory timestamps, so it
cannot see this: if the agent never appended an event, the newest event is old,
and the board says "stale" while the agent works a metre away. That is the right
verdict for the wrong reason, and the wording sends you to the wrong fix.

This module adds the missing evidence — the filesystem — and answers the actual
question: *is the project directory moving while the trajectory is not?*

Design rules:
  - Read-only, no writes, never fails the render (every probe is best-effort).
  - The verdict is a small enum so callers never parse strings.
  - Only *produced* files count. `workflow/runs/*.json` and the index are the
    very thing we are testing, so they must not be allowed to fake activity.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

# How fresh a produced file must be for the project to count as "moving".
ACTIVE_WINDOW_MINUTES = 60
# How quiet the trajectory must be before the mismatch is worth shouting about.
TRAJECTORY_GRACE_MINUTES = 15

# Verdicts. Kept as plain strings for easy JSON round-tripping.
NOT_REPORTING = "not_reporting"      # files moving, trajectory silent  -> ALARM
HEALTHY = "healthy"                  # both moving                      -> ok
NO_ACTIVITY = "no_activity"          # neither moving                   -> idle, fine
QUIET_AFTER_WORK = "quiet_after_work"  # files stopped, trajectory silent -> probably just idle
NEVER_STARTED = "never_started"      # nothing anywhere                 -> nothing to say

# Files that are the reporting channel itself, not evidence of production.
_EXCLUDED_DIRS = {"runs", "__pycache__", ".git", "node_modules"}
_EXCLUDED_NAMES = {"run_index.json", "segments.json"}


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def age_minutes(value: str, *, now: float | None = None) -> int | None:
    """Whole minutes since an ISO timestamp, or None when unparseable."""
    moment = _parse_iso(value)
    if moment is None:
        return None
    reference = now if now is not None else time.time()
    return int((reference - moment.timestamp()) // 60)


def newest_artifact(project_root: str | Path, *, now: float | None = None) -> dict:
    """The most recently written *produced* file under the project.

    `workflow/runs/` is skipped on purpose: a trajectory file is the thing we
    are checking, so letting it count as activity would make the alarm
    self-silencing. Returns {} when nothing qualifies.
    """
    root = Path(project_root)
    if not root.is_dir():
        return {}
    reference = now if now is not None else time.time()
    best: dict = {}
    best_mtime = 0.0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name in _EXCLUDED_NAMES:
            continue
        # Skip the reporting channel and machine noise anywhere in the path.
        if any(part in _EXCLUDED_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = {
                "path": str(path),
                "relative": str(path.relative_to(root)),
                "mtime": mtime,
                "age_minutes": int((reference - mtime) // 60),
            }
    return best


def detect(project_root: str | Path | None, *, newest_event_at: str = "",
           index_updated_at: str = "", now: float | None = None,
           active_window: int = ACTIVE_WINDOW_MINUTES,
           grace: int = TRAJECTORY_GRACE_MINUTES) -> dict:
    """Is this project working without reporting?

    Returns a dict with:
        level    -> one of the verdict constants above
        alarm    -> bool, True only for NOT_REPORTING
        label    -> one short Chinese phrase for a banner headline
        detail   -> one sentence explaining the evidence
        hint     -> what to do about it
        artifact -> the newest produced file (path, relative, age_minutes)
        trajectory_age_minutes / artifact_age_minutes
    """
    if not project_root:
        return _result(
            NO_ACTIVITY, "未检测",
            "未指定项目目录，无法判断是「没在跑」还是「跑了没上报」。",
            "渲染时给出项目根目录（<code>render_run_report.py &lt;项目目录&gt;</code>）即可启用沉默检测。",
        )

    reference = now if now is not None else time.time()
    artifact = newest_artifact(project_root, now=reference)
    artifact_age = artifact.get("age_minutes") if artifact else None

    # The trajectory's own last-written moment: the newer of the last event and
    # the index stamp. Either one moving means the channel is alive.
    event_age = age_minutes(newest_event_at, now=reference)
    index_age = age_minutes(index_updated_at, now=reference)
    candidates = [a for a in (event_age, index_age) if a is not None]
    trajectory_age = min(candidates) if candidates else None

    moving = artifact_age is not None and artifact_age <= active_window
    reporting = trajectory_age is not None and trajectory_age <= max(grace, 0)

    if moving and not reporting:
        silent_for = "从未写入"
        if trajectory_age is not None:
            silent_for = f"{trajectory_age} 分钟没有写入"
        return _result(
            NOT_REPORTING,
            f"疑似在执行但未上报轨迹（近 {active_window} 分钟内仍有文件产出）",
            f"最新产出文件 <code>{_rel(artifact)}</code> 写于 {artifact_age} 分钟前，"
            f"但轨迹通道 {silent_for}。项目在动，看板不知道。",
            "让生产窗口立刻用 <code>append_event.py</code> 补回报；"
            "在补齐之前，本页所有 Gate 结论都不可信——轨迹比现实更乐观。",
            artifact=artifact, trajectory_age=trajectory_age, artifact_age=artifact_age,
        )

    if moving and reporting:
        return _result(
            HEALTHY,
            f"正常（产出与轨迹都在更新）",
            f"最新产出文件写于 {artifact_age} 分钟前，轨迹最后写入 "
            f"{'从未' if trajectory_age is None else str(trajectory_age) + ' 分钟前'}。",
            "",
            artifact=artifact, trajectory_age=trajectory_age, artifact_age=artifact_age,
        )

    if not moving and not reporting:
        if artifact_age is None and trajectory_age is None:
            return _result(
                NEVER_STARTED, "未开始（没有任何产出，也没有任何轨迹）",
                "项目目录里既没有产出文件，也没有轨迹事件。", "",
                artifact=artifact, trajectory_age=trajectory_age, artifact_age=artifact_age,
            )
        return _result(
            QUIET_AFTER_WORK, "已停手（产出与轨迹都不再更新）",
            f"最新产出文件写于 {artifact_age} 分钟前（超过 {active_window} 分钟），"
            f"轨迹同样静止。看起来是正常收工，不是漏报。",
            "若这段确实应该在跑，再检查生产窗口是否已退出。",
            artifact=artifact, trajectory_age=trajectory_age, artifact_age=artifact_age,
        )

    # Files stopped but the trajectory is fresh: worker wrote a closing event.
    return _result(
        QUIET_AFTER_WORK, "已停手（轨迹有新回传，但已无新产出）",
        f"轨迹最后写入 {'从未' if trajectory_age is None else str(trajectory_age) + ' 分钟前'}，"
        f"最新产出文件写于 {artifact_age} 分钟前（超过 {active_window} 分钟）。",
        "",
        artifact=artifact, trajectory_age=trajectory_age, artifact_age=artifact_age,
    )


def _rel(artifact: dict) -> str:
    if not artifact:
        return "-"
    return str(artifact.get("relative") or artifact.get("path") or "-")


def _result(level: str, label: str, detail: str, hint: str, *,
            artifact: dict | None = None, trajectory_age: int | None = None,
            artifact_age: int | None = None) -> dict:
    return {
        "level": level,
        "alarm": level == NOT_REPORTING,
        "label": label,
        "detail": detail,
        "hint": hint,
        "artifact": artifact or {},
        "trajectory_age_minutes": trajectory_age,
        "artifact_age_minutes": artifact_age,
    }


def banner_html(alarm: dict) -> str:
    """A loud, self-contained banner for the top of the page.

    Only renders for a real alarm: a green page must not grow furniture for a
    condition that is not present.
    """
    if not alarm or not alarm.get("alarm"):
        return ""
    from html import escape
    artifact = alarm.get("artifact") or {}
    evidence = ""
    if artifact:
        evidence = (
            f'<div class="ev">证据：<code>{escape(str(artifact.get("relative", "")))}</code>'
            f'　写于 {escape(str(artifact.get("age_minutes", "?")))} 分钟前</div>'
        )
    return f"""
  <details class="silence" role="alert">
    <summary class="shead">⚠ {escape(alarm.get("label", ""))} <span>详情</span></summary>
    <div class="sbody">{alarm.get("detail", "")}</div>
    {evidence}
    <div class="sfix">{alarm.get("hint", "")}</div>
  </details>"""
