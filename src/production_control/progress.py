"""Append one step to a run trace.

Protocol 18 says every completed step must be recorded, and a step with no record
counts as not done. Hand-writing the nested JSON is error-prone, so appending is
one call: the step, the skill that ran it, the protocol documents it read, the
evidence path, and the outcome.

Python-side helper; the CLI wrapper is tools/append_event.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import run_index, run_state, step_registry
from . import qa_policy
from .outcomes import COMPLETING_OUTCOMES, validate_outcome


class MissingEvidenceError(ValueError):
    """A step tried to record itself with no evidence path at all.

    Distinct from FileNotFoundError (a path was given but the file is absent):
    here the field was left empty, which used to be a warning. That made the
    18-rule unenforceable — omitting the field satisfied the checker — and a
    trace with `"evidence": ""` reads as recorded while showing nothing.
    """


class UnknownStepError(ValueError):
    """A step name that no declared step answers to.

    This is the boundary that stops the mistyped-name class of failure. A name
    invented at write time is stored verbatim, and nothing downstream can tell
    it apart from a real step - so the work is recorded and the board shows
    nothing. Refusing here, with the valid list attached, moves the correction
    to the one place where the correct names are known.
    """


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


def resolve_step(step: str, *, off_protocol: bool = False) -> tuple[str, str, dict]:
    """Canonicalise a typed step name.

    Returns `(canonical_skill, step_id, extra_event_fields)`. Raises
    `UnknownStepError` when nothing matches, unless the caller has said
    `off_protocol=True` - which is for a genuinely auxiliary record (a skill
    audit, a one-off probe) that is not one of the declared steps.

    A near-miss spelling is accepted so that one wrong letter cannot silently
    lose a day of work, but it is marked in the trace as `step_matched_fuzzy`
    with the original text kept in `step_as_written`. Guessing quietly would
    trade a loud failure for a silent mis-attribution, which is worse.
    """
    outcome = step_registry.resolve(step)
    if outcome.ok and outcome.step is not None:
        extra: dict = {"step_id": outcome.step.id}
        if not outcome.exact:
            extra["step_matched_fuzzy"] = round(outcome.score, 3)
            extra["step_as_written"] = step
        return outcome.step.skill, outcome.step.id, extra

    if off_protocol:
        return step, "", {"off_protocol": True, "step_as_written": step}

    hints = "；".join(
        f"你写的可能是 {s.id} {s.skill}" for s in outcome.suggestions
    )
    raise UnknownStepError(
        f"UnknownStepError：步骤名「{step}」不在协议声明链内，已拒绝写入。\n"
        "按 18 号规则，轨迹事件必须能用协议步骤名归位——名字写错的事件会被看板"
        "列为「链外」，G1–G6 不会因为它的完成而前进，等于白记。\n"
        f"{hints}\n"
        "可用的名字（第一列是稳定 ID，推荐直接用它，最短也最不容易错）：\n"
        f"{step_registry.format_choices()}\n"
        "确实要记录一个协议链以外的辅助动作，显式加 --off-protocol。"
    )


def append_event(project_root: str | Path, run_id: str, *, step: str, skill_id: str = "",
                 protocol_refs: list[str] | None = None, evidence: str = "",
                 outcome: str = "SUBMITTED_FOR_QA", reason: str = "", validator: str = "",
                 actor: str = "", at: str = "", allow_missing_evidence: bool = False,
                 allow_self_qa: bool = False, role: str = "producer",
                 gate: str = "", off_protocol: bool = False) -> dict:
    """Append one event and return the updated state.

    Every step must name evidence that exists on disk. Two refusals, both at
    write time because that is the only moment the truth is checkable:

      - a path given but not present  -> FileNotFoundError
      - no path at all                -> MissingEvidenceError

    The second one used to be a warning, which made the rule unenforceable: an
    agent could satisfy the checker by simply omitting the field, and a trace
    with `"evidence": ""` looks recorded while showing nothing. Write the
    artefact first, then record the step. Use allow_missing_evidence only when
    the step genuinely produces no artefact of its own.

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

    # Canonicalise first: every refusal below is more useful when it names the
    # step the way the protocol names it, not the way it was typed.
    canonical_step, step_id, extra_fields = resolve_step(step, off_protocol=off_protocol)

    if not allow_missing_evidence:
        if not evidence.strip():
            raise MissingEvidenceError(
                f"步骤 {step} 没有 evidence 路径。按 18 号规则，每一步都必须能追到证据——"
                "证据缺失的轨迹与手写 JSON 无法区分，看板会把没做的事显示成做完了。\n"
                "先把这一步的实际产物／记录写成文件，再用 --evidence 指过去；"
                "确实没有本步产物时，显式传 allow_missing_evidence=True（并接受它会被审计标记）。"
            )
        target = root / evidence
        if not target.is_file():
            raise FileNotFoundError(
                f"证据文件不存在：{target}\n"
                "按 18 号规则，证据必须真实存在——先把这一步的实际产物／记录写成文件，再记事件。"
            )

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
        "step": canonical_step,
        "outcome": outcome,
        "at": at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        # The canonical skill, never whatever was typed: downstream code joins on
        # these strings, and a name that only matches itself is how a recorded
        # step becomes an invisible one. `skill_id` is still accepted for callers
        # that pass it, but the canonical name wins.
        "skill_id": canonical_step,
        "protocol_refs": [{"path": p} for p in (protocol_refs or [])],
        "evidence": evidence,
        "validator": validator,
    }
    event.update(extra_fields)
    if reason:
        event["reason"] = reason
    if actor:
        event["actor"] = actor
    event["role"] = role
    if gate:
        event["gate"] = gate
    if allow_missing_evidence and not evidence.strip():
        # A waiver must be visible in the trace, not silent: otherwise the next
        # reader cannot tell "no artefact exists" from "nobody attached one".
        event["evidence_waived"] = True

    _refuse_self_review(state, event, allow_self_qa=allow_self_qa)

    state.setdefault("events", []).append(event)

    pipeline = state.get("pipeline") or []
    if outcome in COMPLETING_OUTCOMES:
        completed = state.setdefault("completed_steps", [])
        if canonical_step not in completed:
            completed.append(canonical_step)
        remaining = [s for s in pipeline if s not in completed]
        state["current_step"] = remaining[0] if remaining else ""
        # Once everything has run, keep whatever the outcome says: COMPLETED is a
        # clean finish, COMPLETED_WITH_CONTINUITY_CAVEAT finishes with a caveat.
        state["status"] = outcome if not remaining else "RUNNING"
        state.pop("pending_decision", None)
    else:
        # Waiting, blocked, submitted, failed: the segment state IS the outcome.
        state["status"] = outcome
        state["current_step"] = canonical_step
        if reason:
            state["pending_decision"] = reason

    run_state.write_task(path, state)
    index = run_index.load_index(root)
    run_index.register_run(index, state, make_active=state.get("status") != "COMPLETED")
    run_index.save_index(root, index)
    return state
