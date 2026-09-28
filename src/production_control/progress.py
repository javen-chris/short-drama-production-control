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
                 writer_model: str = "",
                 gate: str = "", off_protocol: bool = False,
                 task_id: str = "", version: str = "", qa_level: str = "",
                 qa_conclusion: str = "", elapsed_seconds: int | None = None,
                 execution_model: str = "", issue_id: str = "", qa_attempt: int = 1,
                 blocking_issues: list[str] | None = None, next_step: str = "",
                 affected_files: list[str] | None = None) -> dict:
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

    `writer_model` is the model actually writing the trace. It is deliberately
    separate from `actor`, which records the model that did the work. Only the
    configured QA writer may append to the board, including a producer
    submission relayed by QA.

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
    if not allow_missing_evidence:
        for affected in affected_files or []:
            if not (root / affected).is_file():
                raise FileNotFoundError(f"受影响文件不存在：{root / affected}")

    state = json.loads(path.read_text(encoding="utf-8"))

    contract = state.get("execution_contract") or {}
    if contract and not off_protocol:
        contract_steps = contract.get("steps", [])
        declared = next((item for item in contract_steps if item.get("id") == step_id), None)
        if declared is None:
            raise ValueError(f"STEP_NOT_IN_EXECUTION_CONTRACT：{step_id} 不属于本次 RUN 执行清单。")
        if not declared.get("applicable", False):
            raise ValueError(
                f"STEP_NOT_APPLICABLE：{step_id} 本次不适用：{declared.get('reason', '未说明原因')}"
            )
        if step_id != contract.get("current_step_id"):
            raise ValueError(
                f"STEP_OUT_OF_ORDER：当前合同步骤是 {contract.get('current_step_id') or '无'}，"
                f"拒绝提前记录 {step_id}。"
            )
        if task_id != contract.get("task_id") or version != contract.get("version"):
            raise ValueError("EXECUTION_CONTRACT_MISMATCH：任务 ID 或版本与 RUN 执行合同不一致。")
        if role == qa_policy.PRODUCER:
            if actor.strip().lower() != str(contract.get("execution_model", "")).strip().lower():
                raise PermissionError("EXECUTION_MODEL_MISMATCH：提交者与 RUN 合同中的执行模型声明不一致。")
            if writer_model.strip().lower() != str(contract.get("qa_model", "")).strip().lower():
                raise PermissionError("QA_WRITER_ROUTE_MISMATCH：提交事件必须由合同路由的 QA GPT 写入。")
        elif role == qa_policy.QA:
            if actor.strip().lower() != str(contract.get("qa_model", "")).strip().lower():
                raise PermissionError("QA_ACTOR_ROUTE_MISMATCH：QA actor 不是本 RUN 路由的 GPT 模型。")
            if execution_model.strip().lower() != str(contract.get("execution_model", "")).strip().lower():
                raise ValueError("EXECUTION_MODEL_MISMATCH：QA 声明的执行模型与 RUN 合同不一致。")
        expected_refs = {ref["path"] for ref in declared.get("protocol_refs", [])}
        supplied_refs = {str(ref).replace("\\", "/") for ref in (protocol_refs or [])}
        if not expected_refs.issubset(supplied_refs):
            missing_refs = sorted(expected_refs - supplied_refs)
            raise ValueError("CONTRACT_PROTOCOLS_MISSING：本步骤没有声明读取全部适用协议：" + ", ".join(missing_refs))
        protocol_refs = [dict(ref) for ref in declared.get("protocol_refs", [])]
        protocol_refs.extend({"path": ref} for ref in sorted(supplied_refs - expected_refs))

    validate_outcome(outcome)

    if role == qa_policy.QA:
        required_qa = {
            "task_id": task_id, "version": version, "qa_level": qa_level,
            "qa_conclusion": qa_conclusion, "execution_model": execution_model,
            "next_step": next_step, "affected_files": affected_files,
        }
        missing_qa = [name for name, value in required_qa.items() if not str(value or "").strip()]
        if elapsed_seconds is None or elapsed_seconds < 0:
            missing_qa.append("elapsed_seconds")
        if not affected_files:
            missing_qa.append("affected_files")
        if qa_level not in {"A", "B", "C", "FINAL"}:
            raise ValueError("QA_LEVEL_INVALID：qa_level 必须为 A、B、C 或 FINAL。")
        if qa_conclusion not in {"PASS", "FAIL", "CONDITIONAL", "TIMEOUT"}:
            raise ValueError("QA_CONCLUSION_INVALID：结论必须为 PASS、FAIL、CONDITIONAL 或 TIMEOUT。")
        if missing_qa:
            raise ValueError("QA_METADATA_REQUIRED：QA 事件缺少 " + ", ".join(missing_qa))
        expected_outcomes = {
            "PASS": {"COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT",
                     "USABLE_WITH_SCENE_CONTINUITY_FAIL"},
            "FAIL": {"FAILED"},
            "CONDITIONAL": {"WAITING_APPROVAL"},
            "TIMEOUT": {"WAITING_APPROVAL"},
        }[qa_conclusion]
        if outcome not in expected_outcomes:
            raise ValueError(
                f"QA_OUTCOME_MISMATCH：{qa_conclusion} 与轨迹状态 {outcome} 不匹配。"
            )
        if qa_attempt not in {1, 2}:
            raise ValueError("QA_ATTEMPT_LIMIT：同版本同等级最多一次初审和一次有 issue_id 的复核。")
        if qa_attempt == 2 and not issue_id.strip():
            raise ValueError("QA_ISSUE_ID_REQUIRED：同版本复核必须指定 issue_id。")

    allowed, refusal = qa_policy.may_write(role, outcome)
    if not allowed:
        raise PermissionError(refusal)

    ok_writer, writer_refusal = qa_policy.writer_model_allowed(writer_model)
    if not ok_writer:
        raise PermissionError(writer_refusal)

    if role == qa_policy.PRODUCER:
        expected_writer = qa_policy.qa_model_for_execution(actor)
        if expected_writer is None:
            raise PermissionError(
                f"{qa_policy.WRITER_MODEL_NOT_ALLOWED}：执行模型 {actor or '未提供'} 没有配置 QA 写入路由；"
                "拒绝由生产模型或未知模型直接写看板。"
            )
        if writer_model.strip().lower() != expected_writer:
            raise PermissionError(
                f"{qa_policy.WRITER_MODEL_NOT_ALLOWED}：执行模型 {actor} 的提交必须由其路由 QA 模型 "
                f"{expected_writer} 写入，收到 {writer_model}。"
            )

    if role == qa_policy.QA:
        producer_model = ""
        producer_event = None
        for earlier in reversed(state.get("events") or []):
            if earlier.get("step") == canonical_step and (
                    earlier.get("role") or qa_policy.PRODUCER) == qa_policy.PRODUCER:
                producer_event = earlier
                producer_model = (earlier.get("actor") or "").strip()
                break
        if producer_model and producer_model.strip().lower() == actor.strip().lower():
            raise ValueError(
                f"SELF_QA_VIOLATION：QA 模型 {actor} 与执行模型相同，禁止自审。"
            )
        if execution_model.strip().lower() != producer_model.lower():
            raise ValueError(
                f"QA_EXECUTION_MODEL_MISMATCH：提交记录的执行模型为 {producer_model or '未记录'}，"
                f"本次 QA 声明为 {execution_model or '未提供'}。"
            )
        if producer_event and producer_event.get("version") and producer_event["version"] != version:
            raise ValueError(
                f"QA_VERSION_MISMATCH：提交版本为 {producer_event['version']}，本次 QA 版本为 {version}。"
            )
        if producer_event and producer_event.get("task_id") and producer_event["task_id"] != task_id:
            raise ValueError("QA_TASK_MISMATCH：任务 ID 与该版本提交记录不一致。")
        if producer_event and producer_event.get("qa_level") and producer_event["qa_level"] != qa_level:
            raise ValueError("QA_LEVEL_MISMATCH：QA 等级与该版本提交记录不一致。")
        if producer_event and producer_event.get("affected_files") and sorted(producer_event["affected_files"]) != sorted(affected_files or []):
            raise ValueError("QA_SCOPE_MISMATCH：QA 的 affected_files 必须与该版本提交的文件清单一致。")
        if producer_event:
            expected_writer = qa_policy.qa_model_for_execution(producer_model)
            if (producer_event.get("writer_model") or "").strip().lower() != (expected_writer or ""):
                raise PermissionError(
                    f"{qa_policy.WRITER_MODEL_NOT_ALLOWED}：当前版本提交记录不是由路由 QA 模型 "
                    f"{expected_writer or '写入'} 记录；请由 QA 模型重新登记提交后再审核。"
                )
        qa_allowed, qa_refusal = qa_policy.qa_model_allowed(
            gate, actor, execution_model=producer_model
        )
        if not qa_allowed:
            raise PermissionError(qa_refusal)
        if writer_model.strip().lower() != actor.strip().lower():
            raise PermissionError(
                f"{qa_policy.WRITER_MODEL_NOT_ALLOWED}：QA 模型 {actor} 必须本人写入 QA 结论，"
                f"收到写入者 {writer_model}。"
            )
        prior_reviews = [e for e in state.get("events") or []
                         if e.get("step") == canonical_step
                         and (e.get("role") or qa_policy.PRODUCER) == qa_policy.QA
                         and e.get("version") == version
                         and e.get("qa_level") == qa_level]
        if any(int(e.get("qa_attempt") or 1) == qa_attempt for e in prior_reviews):
            raise ValueError(
                "QA_ATTEMPT_DUPLICATE：此版本此等级的该轮 QA 已记录；稳定版本不得重复调用。"
            )
        if qa_attempt == 2:
            prior_issue_ids = {e.get("issue_id") for e in prior_reviews
                               if e.get("qa_conclusion") in {"FAIL", "TIMEOUT"} and e.get("issue_id")}
            if issue_id not in prior_issue_ids:
                raise ValueError(
                    "QA_REREVIEW_NOT_ALLOWED：同版本复核仅限对已有 FAIL 的同一 issue_id 复核。"
                )

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
        "protocol_refs": [dict(p) if isinstance(p, dict) else {"path": p}
                          for p in (protocol_refs or [])],
        "evidence": evidence,
        "validator": validator,
        "writer_model": writer_model,
    }
    if contract:
        event["contract_id"] = contract.get("contract_id", contract.get("task_id", ""))
    optional_fields = {
        "task_id": task_id, "version": version, "qa_level": qa_level,
        "qa_conclusion": qa_conclusion, "elapsed_seconds": elapsed_seconds,
        "execution_model": execution_model, "issue_id": issue_id,
        "qa_attempt": qa_attempt if role == qa_policy.QA else None,
        "blocking_issues": blocking_issues, "next_step": next_step,
        "affected_files": affected_files,
    }
    event.update({key: value for key, value in optional_fields.items() if value is not None and value != ""})
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

    if contract and not off_protocol:
        contract_item = next((item for item in contract.get("steps", [])
                              if item.get("id") == step_id), None)
        if contract_item is not None:
            if role == qa_policy.PRODUCER and outcome == "SUBMITTED_FOR_QA":
                contract_item["disposition"] = "submitted_for_qa"
                contract["current_owner"] = "qa"
                contract["next_action"] = f"由 {contract.get('qa_model')} 独立审核 {step_id} 当前版本并记录结论"
            elif role == qa_policy.PRODUCER and outcome in {"BLOCKED", "WAITING_APPROVAL", "FAILED"}:
                contract_item["disposition"] = outcome.lower()
                contract["current_owner"] = "user"
                contract["next_action"] = reason or f"处理 {step_id} 的阻断后再继续"
            elif role == qa_policy.QA:
                contract_item["disposition"] = {
                    "COMPLETED": "qa_passed",
                    "FAILED": "qa_failed",
                    "WAITING_APPROVAL": "waiting_decision",
                }.get(outcome, "qa_recorded")
                if outcome == "COMPLETED":
                    current_gates = set(contract_item.get("gate", []))
                    pregen_qa = next((item for item in contract.get("steps", [])
                                      if item.get("mode") == "pre_generation"
                                      and item.get("applicable")
                                      and item.get("disposition") == "pending"
                                      and current_gates.intersection(item.get("gate", []))), None)
                    if pregen_qa:
                        pregen_qa["disposition"] = "qa_passed"
                        pregen_qa["evidence_step_id"] = step_id
                    index = next((i for i, item in enumerate(contract.get("steps", []))
                                  if item.get("id") == step_id), -1)
                    next_item = next((item for item in contract.get("steps", [])[index + 1:]
                                      if item.get("applicable") and item.get("disposition") == "pending"), None)
                    if next_item:
                        contract["current_step_id"] = next_item["id"]
                        if next_item.get("approval"):
                            contract["current_owner"] = "user"
                            contract["next_action"] = f"等待用户确认：{next_item['approval']}"
                        elif next_item.get("mode") in {"pre_generation", "post_generation"}:
                            contract["current_owner"] = "qa"
                            contract["next_action"] = f"由 {contract.get('qa_model')} 执行 {next_item['id']} 独立 QA"
                        else:
                            contract["current_owner"] = "producer"
                            contract["next_action"] = f"执行 {next_item['id']} {next_item['skill']} 并提交证据"
                    else:
                        contract["current_step_id"] = ""
                        contract["current_owner"] = "complete"
                        contract["next_action"] = "本 RUN 的适用步骤已完成；不得据此扩大生成或付费授权"
                elif outcome == "FAILED":
                    contract["current_owner"] = "producer"
                    contract["next_action"] = "汇总问题；修订后递增版本并建立新执行合同，再提交独立 QA"
                else:
                    contract["current_owner"] = "user"
                    contract["next_action"] = next_step or reason or "停止并等待用户决定"

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
