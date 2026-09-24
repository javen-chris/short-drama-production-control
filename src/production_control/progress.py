"""Append one step to a run trace.

Protocol 18 says every completed step must be recorded, and a step with no record
counts as not done. Hand-writing the nested JSON is error-prone, so appending is
one call: the step, the skill that ran it, the protocol documents it read, the
evidence path, and the outcome.

Python-side helper; the CLI wrapper is tools/append_event.py.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

from . import run_index, run_state
from . import qa_policy
from .outcomes import COMPLETING_OUTCOMES, validate_outcome


def _refuse_self_review(state: dict, event: dict, *, allow_self_qa: bool = False) -> None:
    """Refuse a QA write that is not actually a second opinion.

    Two ways this goes wrong, both refused here rather than discovered later:

    - the same model signs off on its own work (SELF_QA_VIOLATION)
    - a QA verdict is recorded for a step nobody ever submitted
      (QA_WITHOUT_SUBMISSION) - passing something that was never handed over is
      not a review, it is a fabrication

    Independence is not recoverable after the fact, so it has to be refused at
    write time: this is the only moment the actor is known for certain.
    """
    if allow_self_qa:
        return
    step = event.get("step")
    role = event.get("role") or qa_policy.PRODUCER
    actor = (event.get("actor") or event.get("validator") or "").strip()
    if not actor:
        return

    if role == qa_policy.QA:
        for earlier in reversed(state.get("events") or []):
            if earlier.get("step") != step:
                continue
            if (earlier.get("role") or qa_policy.PRODUCER) != qa_policy.PRODUCER:
                continue
            producer = (earlier.get("actor") or "").strip()
            if producer and producer == actor:
                raise ValueError(
                    f"SELF_QA_VIOLATION：QA 步骤 {step} 的执行模型 {actor}，与该步骤的生产者"
                    "是同一个模型。协议要求 QA 由不同模型执行。"
                    "确实需要自审时，显式传 allow_self_qa=True。"
                )
            return
        raise ValueError(
            f"QA_WITHOUT_SUBMISSION：步骤 {step} 从来没有生产者提交记录，"
            "不能对它出 QA 结论。先由生产模型写 SUBMITTED_FOR_QA，再由另一个模型 QA。"
        )

    return


def append_event(project_root: str | Path, run_id: str, *, step: str, skill_id: str = "",
                 protocol_refs: list[str] | None = None, evidence: str = "",
                 outcome: str = "SUBMITTED_FOR_QA", reason: str = "", validator: str = "",
                 actor: str = "", at: str = "", allow_missing_evidence: bool = False,
                 allow_self_qa: bool = False, role: str = "producer",
                 gate: str = "") -> dict:
    """Append one event and return the updated state.

    If an evidence path is given it must exist: pointing at a file that is not
    there is how a trace starts claiming work it cannot show. Write the evidence
    first, then record the step. Use allow_missing_evidence only when the step
    genuinely has no artefact of its own.

    `actor` names the model that did the step. It is what makes QA independence
    checkable: a QA event whose actor matches the one that produced the work is a
    model grading its own homework, and is refused unless allow_self_qa is set.

    `role` decides what may be written at all. A producer may submit
    (SUBMITTED_FOR_QA) but never pass; passing is the QA role's to record, and a
    producer that tries is refused with WRITE_AUTHORITY_VIOLATION. That is what
    makes "the producing model cannot sign off on its own work" a property of the
    system rather than a request in a document.
    """
    root = Path(project_root)
    path = run_index.run_path(root, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"没有找到轨迹文件：{path}（先创建该段的运行，或检查 run_id）")

    if evidence and not allow_missing_evidence:
        target = root / evidence
        if not target.is_file():
            raise FileNotFoundError(
                f"证据文件不存在：{target}\n"
                "按 18 号规则，证据必须真实存在——先把这一步的实际产物／记录写成文件，再记事件。"
            )
    if not evidence:
        warnings.warn("这一步没有 evidence 路径；18 号规则要求每步都能追到证据", stacklevel=2)

    state = json.loads(path.read_text(encoding="utf-8"))

    validate_outcome(outcome)

    allowed, refusal = qa_policy.may_write(role, outcome)
    if not allowed:
        raise PermissionError(refusal)
    if role == qa_policy.PRODUCER:
        ok_model, why = qa_policy.producer_model_allowed(actor)
        if not ok_model:
            raise PermissionError(why)

    event = {
        "step": step,
        "outcome": outcome,
        "at": at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "skill_id": skill_id or step,
        "protocol_refs": [{"path": p} for p in (protocol_refs or [])],
        "evidence": evidence,
        "validator": validator,
    }
    if reason:
        event["reason"] = reason
    if actor:
        event["actor"] = actor
    event["role"] = role
    if gate:
        event["gate"] = gate

    _refuse_self_review(state, event, allow_self_qa=allow_self_qa)

    state.setdefault("events", []).append(event)

    pipeline = state.get("pipeline") or []
    if outcome in COMPLETING_OUTCOMES:
        completed = state.setdefault("completed_steps", [])
        if step not in completed:
            completed.append(step)
        remaining = [s for s in pipeline if s not in completed]
        state["current_step"] = remaining[0] if remaining else ""
        # Once everything has run, keep whatever the outcome says: COMPLETED is a
        # clean finish, COMPLETED_WITH_CONTINUITY_CAVEAT finishes with a caveat.
        state["status"] = outcome if not remaining else "RUNNING"
        state.pop("pending_decision", None)
    else:
        # Waiting, blocked, submitted, failed: the segment state IS the outcome.
        state["status"] = outcome
        state["current_step"] = step
        if reason:
            state["pending_decision"] = reason

    run_state.write_task(path, state)
    index = run_index.load_index(root)
    run_index.register_run(index, state, make_active=state.get("status") != "COMPLETED")
    run_index.save_index(root, index)
    return state
