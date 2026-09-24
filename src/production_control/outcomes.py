"""The outcomes a step can have, declared once.

Three places used to disagree about this list:

- the CLI (`tools/append_event.py`) accepted only four values, so real states
  like `SUBMITTED_IN_PROGRESS` could not be recorded with the one command the
  protocol asks for;
- the report (`run_report.py`) labelled only five, silently mislabelling the rest;
- `append_event` ignored anything not in its own short list - it wrote the event
  but left the run's status untouched, so a step could be "recorded" while the
  segment never moved.

Declaring them here and having the other three read from this module is what
keeps them from drifting apart again.
"""
from __future__ import annotations

#: Outcomes that mean "this step is done" - they advance the run.
COMPLETING_OUTCOMES = frozenset({
    "COMPLETED",
    "COMPLETED_WITH_CONTINUITY_CAVEAT",
    "USABLE_WITH_SCENE_CONTINUITY_FAIL",
})

OUTCOME_LABELS = {
    "SUBMITTED_FOR_QA": "已提交，等待 QA",
    "COMPLETED": "已完成（QA 通过）",
    "COMPLETED_WITH_CONTINUITY_CAVEAT": "已完成（连续性存疑，QA 通过）",
    "USABLE_WITH_SCENE_CONTINUITY_FAIL": "可用（场景连续性未过）",
    "SUBMITTED_IN_PROGRESS": "已提交，等待回执",
    "WAITING_APPROVAL": "等待你批准",
    "PAUSED_EXCEPTION": "已挂起（异常）",
    "BLOCKED": "已阻断",
    "FAILED": "失败",
}

#: Accepted values, in reporting order. The CLI builds its choices from this.
OUTCOMES = tuple(OUTCOME_LABELS)


def validate_outcome(outcome: str) -> str:
    """Reject an outcome nobody recognises, instead of quietly ignoring it.

    Silently accepting an unknown state was the worst of the three behaviours:
    the event landed in the trace while the segment status stayed where it was,
    so the run looked recorded but never actually progressed.
    """
    if outcome not in OUTCOME_LABELS:
        raise ValueError(
            f"未知的 outcome：{outcome}\n"
            f"合法值：{', '.join(OUTCOMES)}"
        )
    return outcome
