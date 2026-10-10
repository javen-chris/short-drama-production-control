"""Resume an existing RUN from hash-verified evidence without replaying it."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from . import run_index, task_state, step_registry, protocol_versions


def _event_step_id(event: dict) -> str:
    if event.get("step_id"):
        return str(event["step_id"])
    step = str(event.get("step", ""))
    resolved = step_registry.resolve(step)
    return resolved.step.id if resolved.ok and resolved.step else ""


def _event_evidence_is_current(event: dict, root: Path) -> tuple[bool, str]:
    evidence = event.get("evidence")
    if not isinstance(evidence, str) or not evidence:
        return False, "缺少单一证据路径"
    path = root / evidence
    if not path.is_file():
        return False, "证据文件缺失"
    expected = event.get("evidence_sha256")
    if not expected:
        return False, "历史事件没有证据哈希，不能自动复用"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        return False, "证据内容已变化"
    for relative, digest in (event.get("affected_file_hashes") or {}).items():
        target = root / relative
        if not target.is_file():
            return False, f"依赖产物缺失：{relative}"
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            return False, f"依赖产物已变化：{relative}"
    if event.get("affected_files") and not event.get("affected_file_hashes"):
        return False, "历史事件没有依赖文件哈希，不能自动复用"
    return True, "证据哈希有效"


def resume(project_root: str | Path, run_id: str, *, apply: bool = True) -> dict:
    """Inspect or resume the original RUN; never creates a replacement RUN.

    A resume operation appends a diagnostic record and adjusts only the active
    pointer. It never removes events or resets authorization, budget or submit
    counters. Older evidence without hashes is deliberately treated as unknown.
    """
    root = Path(project_root).resolve()
    path = run_index.run_path(root, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"RUN_NOT_FOUND: {path}")
    state = task_state.read_task(path)
    contract = state.get("execution_contract") or {}
    steps = contract.get("steps") or []
    events = state.get("events") or []
    if not steps:
        return {"run_id": run_id, "status": "LEGACY_INSPECT_ONLY",
                "current_step_id": state.get("current_step", ""),
                "reason": "该旧 RUN 无执行合同；保留原位置，不能自动重建新合同。"}

    if contract.get("current_owner") == "user" or state.get("status") in {"WAITING_APPROVAL", "BLOCKED", "PAUSED_EXCEPTION"}:
        return {"run_id": run_id, "status": "WAITING_DECISION",
                "current_step_id": contract.get("current_step_id", ""),
                "reason": state.get("pending_decision") or "等待用户决定；不执行任何依赖步骤。"}
    if contract.get("current_owner") == "qa":
        return {"run_id": run_id, "status": "WAITING_QA",
                "current_step_id": contract.get("current_step_id", ""),
                "reason": "产物已提交给独立 QA；恢复时不重复生产或 QA。"}

    submitted_id = contract.get("provider_task_id") or next((e.get("provider_task_id") for e in reversed(events)
        if e.get("outcome") == "TASK_SUBMITTED" and e.get("provider_task_id")), "")
    if submitted_id:
        terminal = next((e for e in reversed(events) if e.get("provider_task_id") == submitted_id
                         and e.get("outcome") in {"TASK_SUCCEEDED", "TASK_FAILED", "TASK_UNVERIFIED"}), None)
        if terminal:
            status = {"TASK_SUCCEEDED": "COMPLETED", "TASK_FAILED": "PROVIDER_FAILED",
                      "TASK_UNVERIFIED": "RESULT_UNVERIFIED"}[terminal["outcome"]]
            return {"run_id": run_id, "status": status,
                    "provider_task_id": submitted_id, "provider_status": terminal.get("provider_status", ""),
                    "output_urls": terminal.get("output_urls", []),
                    "reason": "供应商终态已记录；恢复不会重复提交或更改已结束 RUN。"}
        monitor = next((s for s in steps if s.get("display_id") == "G6-S12"), None)
        if monitor and monitor.get("applicable"):
            target_step, reason = monitor, "已有真实 Task ID；只恢复状态查询，不重复提交。"
        else:
            return {"run_id": run_id, "status": "SUBMITTED_TASK_REQUIRES_QUERY",
                    "provider_task_id": submitted_id,
                    "reason": "RUN 已提交；不得创建新提交。"}
    else:
        target_step = None
        reason = "第一个缺失或失效步骤"
        drift = protocol_versions.check_current(contract)
        if drift:
            return {"run_id": run_id, "status": "PROTOCOL_MIGRATION_REQUIRED",
                    "current_step_id": contract.get("current_step_id", ""), "errors": drift}
        for step in steps:
            if not step.get("applicable"):
                continue
            disposition = step.get("disposition", "pending")
            if disposition in {"pending", "not_applicable"}:
                continue
            sid = step.get("id")
            candidates = [e for e in events if _event_step_id(e) == sid]
            # A QA step is reusable only after a PASS conclusion; a fact step
            # requires its own completion outcome.
            candidate = next((e for e in reversed(candidates)
                              if e.get("outcome") in {"COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT",
                                  "USABLE_WITH_SCENE_CONTINUITY_FAIL", "STEP_COMPLETED", "TASK_SUBMITTED",
                                  "TASK_SUCCEEDED", "TASK_FAILED"}
                              and (step.get("mode") != "pre_generation" or e.get("qa_conclusion") == "PASS")), None)
            if candidate is None:
                target_step = step
                reason = "步骤没有可复用的完成事件"
                break
            valid, why = _event_evidence_is_current(candidate, root)
            if not valid:
                target_step = step
                reason = why
                break
        if target_step is None:
            target_step = next((s for s in steps if s.get("applicable") and s.get("disposition") == "pending"), None)

    target_id = target_step.get("id") if target_step else ""
    record = {"at": datetime.now(timezone.utc).isoformat(), "from_step_id": contract.get("current_step_id", ""),
              "to_step_id": target_id, "reason": reason,
              "provider_task_id": submitted_id or None}
    result = {"run_id": run_id, "status": "READY" if target_id else "COMPLETED",
              "current_step_id": target_id, "display_id": target_step.get("display_id", "") if target_step else "",
              "skill": target_step.get("skill", "") if target_step else "", "reason": reason,
              "provider_task_id": submitted_id or None}
    if apply and target_id:
        contract["current_step_id"] = target_id
        contract["current_owner"] = "executor" if target_id == "S12" and submitted_id else "producer"
        contract["next_action"] = reason
        state["current_step"] = target_step.get("skill", target_id)
        state["checkpoint"] = state["current_step"]
        state["status"] = "SUBMITTED_IN_PROGRESS" if submitted_id else "RUNNING"
        state.setdefault("resume_history", []).append(record)
        task_state.write_task(path, state)
    return result
