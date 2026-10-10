"""Reconcile one run against the steps the protocol declares.

`verify_run_compliance` checks the steps the run itself listed in `pipeline`.
That is self-certification: declare a short list, pass. The authoritative list
lives in `skills/skill-chain.json`, so this module audits against *that* and
reports, per declared step, both the claim and the proof.

Four verdicts, and the interesting ones are the mismatches:

    OK                    claimed and provable
    CLAIMED_NO_EVIDENCE   claimed, but nothing on disk backs it up
    CLAIMED_NO_READ       provable, but the step never recorded reading its protocol
    NOT_CLAIMED           the protocol requires it and it never happened
    EXTRA                 claimed a step the protocol does not declare

`CLAIMED_NO_EVIDENCE` is the one that matters. It is the shape of every incident
so far: a step is written down as done, and the artefact it should have produced
is not there.

The same module answers the second question nobody was asking: *who* did the QA?
Protocol requires QA by a different model than the one that produced the work, so
a QA event whose actor equals the producer's actor is a self-review, not a review.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import step_registry
from .run_compliance import STEP_PROTOCOL_REQUIREMENTS, missing_required_reads

CHAIN_RELPATH = "skills/skill-chain.json"

# Steps the chain marks as QA. Kept as a set so adding post-generation modes to
# the chain does not silently stop being audited.
QA_MODES = {"pre_generation", "post_generation"}

#: Outcomes a producer may record for a step it is handing over. COMPLETED is in
#: this set only for traces written before write-authority separation existed -
#: a producer can no longer write it, and such an event is treated as a claim
#: that was never QA'd, not as a pass.
PRODUCER_OUTCOMES = frozenset({
    "STEP_COMPLETED", "SUBMITTED_FOR_QA", "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT",
    "USABLE_WITH_SCENE_CONTINUITY_FAIL", "TASK_SUBMITTED", "SUBMITTED_IN_PROGRESS",
    "TASK_SUCCEEDED", "TASK_FAILED",
})
QA_PASS_OUTCOMES = frozenset({
    "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT", "USABLE_WITH_SCENE_CONTINUITY_FAIL",
})

OK = "OK"
CLAIMED_NO_EVIDENCE = "CLAIMED_NO_EVIDENCE"
CLAIMED_NO_READ = "CLAIMED_NO_READ"
NOT_CLAIMED = "NOT_CLAIMED"
NOT_APPLICABLE = "NOT_APPLICABLE"
EXTRA = "EXTRA"

INDEPENDENT = "INDEPENDENT"
SELF_QA_VIOLATION = "SELF_QA_VIOLATION"
QA_ACTOR_UNKNOWN = "QA_ACTOR_UNKNOWN"
QA_ROUTE_VIOLATION = "QA_ROUTE_VIOLATION"
QA_NOT_RUN = "QA_NOT_RUN"
NOT_SUBMITTED = "NOT_SUBMITTED"
AWAITING_QA = "AWAITING_QA"
QA_PASSED = "QA_PASSED"
QA_FAILED = "QA_FAILED"

QA_STEP_LABELS = {
    NOT_SUBMITTED: "未提交",
    AWAITING_QA: "已提交，等待 QA",
    QA_PASSED: "QA 通过",
    QA_FAILED: "QA 不通过",
}

PASS = "PASS"
NON_COMPLIANT = "NON_COMPLIANT"
IN_PROGRESS = "IN_PROGRESS"

VERDICT_LABELS = {
    OK: "已完成且有实证",
    CLAIMED_NO_EVIDENCE: "声称完成但无实证",
    CLAIMED_NO_READ: "有实证但未记录协议读取",
    NOT_CLAIMED: "协议要求但未做",
    NOT_APPLICABLE: "本次不适用",
    EXTRA: "不在协议声明链内",
}

QA_LABELS = {
    INDEPENDENT: "独立模型 QA",
    SELF_QA_VIOLATION: "自审（同一模型）",
    QA_ACTOR_UNKNOWN: "无法判定执行模型",
    QA_ROUTE_VIOLATION: "QA 模型或轨迹写入者不符合路由规则",
    QA_NOT_RUN: "未做 QA",
}


def console_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path)
    return Path(__file__).resolve().parents[2]


def load_chain(console: str | Path | None = None) -> dict:
    chain_path = console_root(console) / CHAIN_RELPATH
    if not chain_path.is_file():
        return {}
    return json.loads(chain_path.read_text(encoding="utf-8"))


def declared_steps(chain: dict | None = None) -> list[dict]:
    """The protocol's step list, in order, de-duplicated by name.

    A step may appear twice in the chain (pre- and post-generation QA). The first
    appearance fixes the order; the extra occurrence contributes its mode, so a
    later pass can tell the two QA rounds apart.
    """
    chain = chain if chain is not None else load_chain()
    order: list[str] = []
    merged: dict[str, dict] = {}
    for item in chain.get("steps", []) or []:
        name = item.get("skill")
        if not name:
            continue
        if name not in merged:
            order.append(name)
            merged[name] = {"step": name, "modes": [], "when": item.get("when", ""),
                            "provider": item.get("provider", "")}
        if item.get("mode"):
            merged[name]["modes"].append(item["mode"])
    return [merged[name] for name in order]


def _completed_event(state: dict, step: str) -> dict | None:
    from .outcomes import COMPLETING_OUTCOMES
    for event in reversed(state.get("events", []) or []):
        if event.get("step") == step and event.get("outcome") in COMPLETING_OUTCOMES:
            return event
    return None


def _producer_event(state: dict, step: str) -> dict | None:
    """The event where the producing model handed this step over."""
    from . import qa_policy

    for event in reversed(state.get("events") or []):
        if event.get("step") != step:
            continue
        if (event.get("role") or qa_policy.PRODUCER) == qa_policy.QA:
            continue
        return event
    return None


def _qa_event(state: dict, step: str) -> dict | None:
    """The event where a different model recorded a verdict on this step."""
    from . import qa_policy

    for event in reversed(state.get("events") or []):
        if event.get("step") != step:
            continue
        if (event.get("role") or qa_policy.PRODUCER) == qa_policy.QA:
            return event
    return None


def _any_event(state: dict, step: str) -> dict | None:
    for event in reversed(state.get("events", []) or []):
        if event.get("step") == step:
            return event
    return None


def _read_paths(event: dict) -> set[str]:
    refs: set[str] = set()
    for item in event.get("protocol_refs", []) or []:
        if isinstance(item, str):
            refs.add(item)
        elif isinstance(item, dict) and item.get("path"):
            refs.add(item["path"])
    return refs


def _evidence_ok(event: dict, root: Path | None) -> bool:
    """A claim is provable when the artefact it names is really there."""
    evidence = event.get("evidence") or ""
    if not evidence:
        return False
    if root is None:
        return True
    # Older agents sometimes stored several evidence entries in one event.
    # Treat those as a set of references; an invalid member must not crash the
    # entire project dashboard while the audit still reports the claim safely.
    references = evidence if isinstance(evidence, list) else [evidence]
    return all(isinstance(reference, str) and reference.strip()
               and (root / reference).exists() for reference in references)


def audit_steps(state: dict, project_root: str | Path | None = None,
                chain: dict | None = None) -> dict:
    """Per-declared-step reconciliation of claim against proof."""
    root = Path(project_root) if project_root else None
    declared = declared_steps(chain)
    declared_names = {row["step"] for row in declared}
    rows: list[dict] = []
    qa_states = {row["step"]: row["state"] for row in audit_qa_passes(state, root)["rows"]}

    for item in declared:
        step = item["step"]
        disposition = (state.get("step_dispositions") or {}).get(step, {})
        producer = _producer_event(state, step)
        reviewer = _qa_event(state, step)
        claimed = producer is not None and producer.get("outcome") in PRODUCER_OUTCOMES

        row = {
            "step": step,
            "modes": item["modes"],
            "claimed": claimed,
            "outcome": (producer or {}).get("outcome", ""),
            "at": (producer or {}).get("at", ""),
            "evidence": (producer or {}).get("evidence", ""),
            "actor": (producer or {}).get("actor", ""),
            "validator": (producer or {}).get("validator", ""),
            # A step is only "passed" when someone other than the producer says
            # so. A producer's own COMPLETED is a claim, and stays a claim.
            "qa_passed": qa_states.get(step) == QA_PASSED,
            "qa_failed": qa_states.get(step) in {QA_FAILED, "QA_INVALID"},
            "qa_actor": (reviewer or {}).get("actor", ""),
            "gate": (producer or {}).get("gate", "") or (reviewer or {}).get("gate", ""),
            # How the recorded name got here. A step that was written under a
            # near-miss spelling is still the right step, but a reader deserves to
            # know the trace was corrected rather than typed correctly.
            "step_as_written": (producer or {}).get("step_as_written", ""),
            "step_matched_fuzzy": (producer or {}).get("step_matched_fuzzy", 0),
            "step_id": (producer or {}).get("step_id", "") or disposition.get("step_id", ""),
            "missing_reads": [],
        }

        if disposition and not disposition.get("applicable", True) and producer is None:
            row["verdict"] = NOT_APPLICABLE
            row["reason"] = disposition.get("reason", "本次执行合同标记为不适用")
            rows.append(row)
            continue

        if not claimed:
            # Blocked or waiting: not a claim, but still progress information.
            if producer is None:
                producer = _any_event(state, step)
            row["verdict"] = NOT_CLAIMED
            row["outcome"] = (producer or {}).get("outcome", row["outcome"])
            rows.append(row)
            continue

        if not _evidence_ok(producer, root):
            row["verdict"] = CLAIMED_NO_EVIDENCE
            row["evidence_ok"] = False
            rows.append(row)
            continue

        row["evidence_ok"] = True
        row["missing_reads"] = missing_required_reads(producer, step)
        row["verdict"] = CLAIMED_NO_READ if row["missing_reads"] else OK
        rows.append(row)

    # Events whose step name the protocol does not declare. These used to be
    # dropped unless they said COMPLETED, which made the board look frozen while
    # an agent was in fact writing a dozen events: the work was real, the names
    # were invented, and the board showed neither. A board that hides activity it
    # cannot categorise is worse than one that shows it as uncategorised - so
    # every undeclared step is surfaced, whatever its outcome.
    seen_extra: dict[str, dict] = {}
    for event in state.get("events", []) or []:
        step = event.get("step")
        if not step or step in declared_names:
            continue
        seen_extra[step] = event  # later events win; the dict keeps the latest
    for step, event in seen_extra.items():
        rows.append({
            "step": step,
            "modes": [],
            "claimed": True,
            "outcome": event.get("outcome", ""),
            "at": event.get("at", ""),
            "evidence": event.get("evidence", ""),
            "reason": event.get("reason", ""),
            "actor": event.get("actor", ""),
            "validator": event.get("validator", ""),
            "gate": event.get("gate", ""),
            "missing_reads": [],
            "evidence_ok": _evidence_ok(event, root),
            "verdict": EXTRA,
        })

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    return {"rows": rows, "counts": counts, "declared_total": len(declared)}


def audit_qa_independence(state: dict, chain: dict | None = None) -> dict:
    """Was the QA done by something other than the thing that did the work?

    Protocol requires QA by a different model. If both events name the same
    actor, that is a model grading its own homework, and it is reported as a
    violation rather than a pass. Missing actor names are not treated as a pass
    either - unverifiable independence is not independence.
    """
    qa_steps = {row["step"] for row in declared_steps(chain) if set(row["modes"]) & QA_MODES}
    if not qa_steps:
        # Without a chain the modes are not available, so ask the registry: a step
        # is a QA step when the chain declares it with a QA mode.
        qa_steps = {s.skill for s in step_registry.qa_steps()}

    events = state.get("events", []) or []
    rounds: list[dict] = []

    for index, event in enumerate(events):
        if event.get("step") not in qa_steps or event.get("outcome") != "COMPLETED":
            continue
        qa_actor = (event.get("actor") or event.get("validator") or "").strip()
        producer_actor = ""
        producer_writer = ""
        producer_step = ""
        for earlier in reversed(events[:index]):
            if earlier.get("step") in qa_steps:
                continue
            if earlier.get("outcome") not in PRODUCER_OUTCOMES:
                continue
            producer_step = earlier.get("step", "")
            producer_actor = (earlier.get("actor") or "").strip()
            producer_writer = (earlier.get("writer_model") or "").strip()
            break

        if not qa_actor or not producer_actor:
            status = QA_ACTOR_UNKNOWN
        elif qa_actor == producer_actor:
            status = SELF_QA_VIOLATION
        else:
            from . import qa_policy
            allowed, _ = qa_policy.qa_model_allowed(
                event.get("gate", ""), qa_actor, execution_model=producer_actor,
                final_packet=bool(event.get('reviewed_packet_sha256'))
            )
            expected_writer = qa_policy.qa_model_for_execution(producer_actor, final_packet=bool(event.get('reviewed_packet_sha256')))
            if (not allowed or (event.get("writer_model") or "").strip().lower() != qa_actor.lower()
                    or producer_writer.lower() != (expected_writer or "")):
                status = QA_ROUTE_VIOLATION
            else:
                status = INDEPENDENT

        rounds.append({"at": event.get("at", ""), "qa_actor": qa_actor,
                       "producer_actor": producer_actor, "producer_step": producer_step,
                       "status": status})

    if not rounds:
        produced = any(e.get("outcome") == "COMPLETED" for e in events)
        return {"status": QA_NOT_RUN if produced else QA_NOT_RUN, "label": QA_LABELS[QA_NOT_RUN],
                "rounds": [], "independent": False}

    worst = INDEPENDENT
    for round_ in rounds:
        if round_["status"] != INDEPENDENT:
            worst = round_["status"]
            break
    return {"status": worst, "label": QA_LABELS[worst], "rounds": rounds,
            "independent": worst == INDEPENDENT}


def audit_qa_passes(state: dict, project_root: str | Path | None = None,
                    policy: dict | None = None) -> dict:
    """Per-step QA state: submitted, passed, failed, or never handed over.

    A step only counts as passed when a *different* model recorded the verdict.
    A COMPLETED written by the producer is not a pass - it is a claim, and it is
    shown as one. That distinction is the reason this module exists: the board
    used to treat the claim as the outcome.
    """
    from . import qa_policy

    policy = policy if policy is not None else qa_policy.load_policy()
    by_step: dict[str, dict] = {}
    order: list[str] = []

    events = state.get("events", []) or []
    for event_index, event in enumerate(events):
        step = event.get("step")
        if not step:
            continue
        if step not in by_step:
            order.append(step)
            by_step[step] = {"step": step, "producer_actor": "", "qa_actor": "",
                             "gate": "", "at": "", "qa_at": "", "state": NOT_SUBMITTED,
                             "task_id": "", "version": "", "qa_level": "",
                             "elapsed_seconds": None, "qa_conclusion": ""}
        row = by_step[step]
        role = event.get("role") or qa_policy.PRODUCER
        outcome = event.get("outcome") or ""

        if role == qa_policy.QA:
            producer_event = next((e for e in reversed(events[:event_index])
                                   if e.get("step") == step
                                   and (e.get("role") or qa_policy.PRODUCER) == qa_policy.PRODUCER), None)
            producer = (producer_event or {}).get("actor", "")
            routed, _ = qa_policy.qa_model_allowed(
                event.get("gate", ""), event.get("actor", ""),
                policy=policy, execution_model=producer, final_packet=bool(event.get('reviewed_packet_sha256')),
            )
            expected_writer = qa_policy.qa_model_for_execution(producer, final_packet=bool(event.get('reviewed_packet_sha256')))
            writer = (event.get("writer_model") or "").strip()
            metadata_ok = all(event.get(k) for k in (
                "task_id", "version", "qa_level", "qa_conclusion", "next_step"
            ))
            metadata_ok = metadata_ok and type(event.get("elapsed_seconds")) is int
            metadata_ok = metadata_ok and isinstance(event.get("blocking_issues"), list)
            metadata_ok = metadata_ok and isinstance(event.get("affected_files"), list) and bool(event["affected_files"])
            producer_writer = ((producer_event or {}).get("writer_model") or "").strip().lower()
            contract = state.get("execution_contract") or {}
            contract_step = next((item for item in contract.get("steps", [])
                                  if item.get("id") == event.get("step_id")), None)
            contract_mismatch = bool(contract) and (
                contract_step is None or not contract_step.get("applicable", False)
                or event.get("contract_id") not in (None, "", contract.get("contract_id", contract.get("task_id")))
                or (producer_event or {}).get("contract_id") not in (
                    None, "", contract.get("contract_id", contract.get("task_id")))
                or event.get("task_id") != contract.get("task_id")
                or event.get("version") != contract.get("version")
                or (event.get("actor") or "").strip().lower() != str(contract.get("qa_model", "")).lower()
                or (event.get("writer_model") or "").strip().lower() != str(contract.get("qa_model", "")).lower()
                or (event.get("execution_model") or "").strip().lower() != str(contract.get("execution_model", "")).lower()
                or (producer_event or {}).get("task_id") != contract.get("task_id")
                or (producer_event or {}).get("version") != contract.get("version")
                or ((producer_event or {}).get("actor") or "").strip().lower()
                   != str(contract.get("execution_model", "")).lower()
            )
            prior_reviews = [e for e in events[:event_index]
                             if e.get("step") == step
                             and (e.get("role") or qa_policy.PRODUCER) == qa_policy.QA
                             and e.get("version") == event.get("version")
                             and e.get("qa_level") == event.get("qa_level")]
            attempt = event.get("qa_attempt", 1)
            duplicate_attempt = any(e.get("qa_attempt", 1) == attempt for e in prior_reviews)
            retry_issue_ok = attempt == 1 or any(
                e.get("qa_attempt", 1) == 1
                and e.get("qa_conclusion") in {"FAIL", "TIMEOUT"}
                and e.get("issue_id") == event.get("issue_id")
                and bool(event.get("issue_id")) for e in prior_reviews
            )
            outcome_ok = {
                "PASS": outcome in QA_PASS_OUTCOMES,
                "FAIL": outcome == "FAILED",
                "CONDITIONAL": outcome == "WAITING_APPROVAL",
                "TIMEOUT": outcome == "WAITING_APPROVAL",
            }.get(event.get("qa_conclusion"), False)
            if event.get("qa_level") == "A" and (event.get("elapsed_seconds") or 0) > 180:
                outcome_ok = outcome_ok and event.get("qa_conclusion") == "TIMEOUT"
            if (contract_mismatch or not routed or writer.lower() != (event.get("actor") or "").strip().lower()
                    or producer_writer != (expected_writer or "") or not metadata_ok
                    or (event.get("execution_model") or "").strip().lower() != producer.strip().lower()
                    or (producer_event or {}).get("version") not in (None, "", event.get("version"))
                    or sorted((producer_event or {}).get("affected_files") or []) != sorted(event.get("affected_files") or [])
                    or event.get("qa_level") not in {"A", "B", "C", "FINAL"}
                    or not outcome_ok or duplicate_attempt or not retry_issue_ok):
                row["state"], row["qa_actor"] = "QA_INVALID", event.get("actor", "")
                row["qa_error"] = "QA 路由、写入身份或版本/等级/耗时元数据不合规"
                row["qa_at"], row["gate"] = event.get("at", ""), event.get("gate", "") or row["gate"]
                row["task_id"], row["version"] = event.get("task_id", ""), event.get("version", "")
                row["qa_level"], row["elapsed_seconds"] = event.get("qa_level", ""), event.get("elapsed_seconds")
                row["qa_conclusion"] = event.get("qa_conclusion", "")
                continue
            row["task_id"], row["version"] = event.get("task_id", ""), event.get("version", "")
            row["qa_level"], row["elapsed_seconds"] = event.get("qa_level", ""), event.get("elapsed_seconds")
            row["qa_conclusion"] = event.get("qa_conclusion", "")
            if outcome == "FAILED":
                row["state"], row["qa_actor"] = "QA_FAILED", event.get("actor", "")
                row["qa_at"], row["gate"] = event.get("at", ""), event.get("gate", "") or row["gate"]
            elif outcome in ("PASS", "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT",
                             "USABLE_WITH_SCENE_CONTINUITY_FAIL"):
                row["state"], row["qa_actor"] = "QA_PASSED", event.get("actor", "")
                row["qa_at"], row["gate"] = event.get("at", ""), event.get("gate", "") or row["gate"]
            elif outcome == "WAITING_APPROVAL":
                row["state"], row["qa_actor"] = "QA_CONDITIONAL", event.get("actor", "")
                row["qa_at"], row["gate"] = event.get("at", ""), event.get("gate", "") or row["gate"]
            continue

        # producer side: anything that claims the step got somewhere
        if outcome in ("SUBMITTED_FOR_QA",) or outcome in (
                "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT", "USABLE_WITH_SCENE_CONTINUITY_FAIL"):
            if row["state"] == NOT_SUBMITTED:
                row["state"] = "AWAITING_QA"
            row["producer_actor"] = event.get("actor", "") or row["producer_actor"]
            row["at"] = event.get("at", "") or row["at"]
            row["gate"] = event.get("gate", "") or row["gate"]

    rows = [by_step[step] for step in order]
    return {
        "rows": rows,
        "submitted": sum(1 for r in rows if r["state"] != NOT_SUBMITTED),
        "passed": sum(1 for r in rows if r["state"] == "QA_PASSED"),
        "failed": sum(1 for r in rows if r["state"] == "QA_FAILED"),
        "invalid": sum(1 for r in rows if r["state"] == "QA_INVALID"),
        "conditional": sum(1 for r in rows if r["state"] == "QA_CONDITIONAL"),
        "awaiting": sum(1 for r in rows if r["state"] == "AWAITING_QA"),
    }


def audit_run(state: dict, project_root: str | Path | None = None,
              chain: dict | None = None) -> dict:
    """Steps plus QA independence, with the errors a gate would refuse on.

    Three failure shapes, in increasing severity:

    - claimed a step with nothing on disk to show for it
    - claimed steps the protocol does not declare, which means the protocol's
      own steps were replaced rather than followed
    - declared steps that never happened at all, on a run that calls itself done
    """
    chain = chain if chain is not None else load_chain()
    steps = audit_steps(state, project_root, chain)
    qa = audit_qa_independence(state, chain)
    counts = steps["counts"]

    errors: list[str] = []
    warnings: list[str] = []

    for row in steps["rows"]:
        if row["verdict"] == CLAIMED_NO_EVIDENCE:
            errors.append(f"{row['step']}: CLAIMED_NO_EVIDENCE - 声称完成，但证据文件不存在")
        elif row["verdict"] == CLAIMED_NO_READ:
            errors.append(f"{row['step']}: CLAIMED_NO_READ - 未记录读取 "
                          f"{'、'.join(row['missing_reads'])}")

    extra = [row["step"] for row in steps["rows"] if row["verdict"] == EXTRA]
    missing = [row["step"] for row in steps["rows"] if row["verdict"] == NOT_CLAIMED]
    status = state.get("status") or ""
    finished = status.startswith("COMPLETED")

    if extra:
        errors.append(
            f"OUT_OF_CHAIN_STEPS - 记录了 {len(extra)} 个协议未声明的步骤：{'、'.join(extra)}。"
            "协议声明的步骤被替换了，而不是被遵循。"
        )
    if missing and counts.get(OK, 0) + counts.get(CLAIMED_NO_EVIDENCE, 0) == 0 and extra:
        errors.append(
            f"PROTOCOL_BYPASSED - 协议声明的 {steps['declared_total']} 步一个都没记录，"
            "轨迹里只有链外步骤。这不是进度落后，是没有按协议做。"
        )
    if finished and missing:
        errors.append(
            f"PROTOCOL_STEPS_INCOMPLETE - 本次已标记完成，但协议声明的 {len(missing)} 步没有记录："
            f"{'、'.join(missing)}"
        )

    if qa["status"] == SELF_QA_VIOLATION:
        errors.append("SELF_QA_VIOLATION - QA 与生产者是同一个模型（"
                      f"{qa['rounds'][0]['qa_actor']}），不构成独立 QA")
    elif qa["status"] == QA_ACTOR_UNKNOWN:
        errors.append("QA_ACTOR_UNKNOWN - 事件未记录执行模型，无法证明 QA 独立")
    elif qa["status"] == QA_ROUTE_VIOLATION:
        errors.append("QA_ROUTE_VIOLATION - QA 模型或轨迹写入者不符合当前独立模型路由")
    elif qa["status"] == QA_NOT_RUN:
        line = "QA_NOT_RUN - 轨迹里没有任何 QA 事件"
        if any(e.get("outcome") == "COMPLETED" for e in state.get("events", []) or []):
            errors.append(line + "；就已经记录的工作而言，没有任何 QA")
        else:
            warnings.append(line)

    if errors:
        verdict = NON_COMPLIANT
    elif finished:
        verdict = PASS
    else:
        verdict = IN_PROGRESS

    return {"steps": steps, "qa": qa, "errors": errors, "warnings": warnings,
            "missing_steps": missing, "out_of_chain_steps": extra,
            "status": verdict}
