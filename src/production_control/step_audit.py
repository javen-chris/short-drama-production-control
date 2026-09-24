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

from .run_compliance import STEP_PROTOCOL_REQUIREMENTS

CHAIN_RELPATH = "skills/skill-chain.json"

# Steps the chain marks as QA. Kept as a set so adding post-generation modes to
# the chain does not silently stop being audited.
QA_MODES = {"pre_generation", "post_generation"}

#: Outcomes a producer may record for a step it is handing over. COMPLETED is in
#: this set only for traces written before write-authority separation existed -
#: a producer can no longer write it, and such an event is treated as a claim
#: that was never QA'd, not as a pass.
PRODUCER_OUTCOMES = frozenset({
    "SUBMITTED_FOR_QA", "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT",
    "USABLE_WITH_SCENE_CONTINUITY_FAIL",
})
QA_PASS_OUTCOMES = frozenset({
    "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT", "USABLE_WITH_SCENE_CONTINUITY_FAIL",
})

OK = "OK"
CLAIMED_NO_EVIDENCE = "CLAIMED_NO_EVIDENCE"
CLAIMED_NO_READ = "CLAIMED_NO_READ"
NOT_CLAIMED = "NOT_CLAIMED"
EXTRA = "EXTRA"

INDEPENDENT = "INDEPENDENT"
SELF_QA_VIOLATION = "SELF_QA_VIOLATION"
QA_ACTOR_UNKNOWN = "QA_ACTOR_UNKNOWN"
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
    EXTRA: "不在协议声明链内",
}

QA_LABELS = {
    INDEPENDENT: "独立模型 QA",
    SELF_QA_VIOLATION: "自审（同一模型）",
    QA_ACTOR_UNKNOWN: "无法判定执行模型",
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
    for event in reversed(state.get("events", []) or []):
        if event.get("step") == step and event.get("outcome") == "COMPLETED":
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
    return (root / evidence).exists()


def audit_steps(state: dict, project_root: str | Path | None = None,
                chain: dict | None = None) -> dict:
    """Per-declared-step reconciliation of claim against proof."""
    root = Path(project_root) if project_root else None
    declared = declared_steps(chain)
    declared_names = {row["step"] for row in declared}
    rows: list[dict] = []

    for item in declared:
        step = item["step"]
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
            "qa_passed": bool(reviewer and reviewer.get("outcome") in QA_PASS_OUTCOMES),
            "qa_failed": bool(reviewer and reviewer.get("outcome") == "FAILED"),
            "qa_actor": (reviewer or {}).get("actor", ""),
            "gate": (producer or {}).get("gate", "") or (reviewer or {}).get("gate", ""),
            "missing_reads": [],
        }

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
        recorded = _read_paths(producer)
        required = set(STEP_PROTOCOL_REQUIREMENTS.get(step, []))
        row["missing_reads"] = sorted(required - recorded)
        row["verdict"] = CLAIMED_NO_READ if row["missing_reads"] else OK
        rows.append(row)

    for event in state.get("events", []) or []:
        step = event.get("step")
        if not step or step in declared_names:
            continue
        if event.get("outcome") != "COMPLETED":
            continue
        if any(r["step"] == step for r in rows):
            continue
        rows.append({"step": step, "modes": [], "claimed": True, "outcome": "COMPLETED",
                     "at": event.get("at", ""), "evidence": event.get("evidence", ""),
                     "actor": event.get("actor", ""), "validator": event.get("validator", ""),
                     "missing_reads": [], "evidence_ok": _evidence_ok(event, root),
                     "verdict": EXTRA})

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
        # Without a chain we cannot say which steps are QA; fall back to the name
        # the protocol has always used.
        qa_steps = {"short-drama-production-qa"}

    events = state.get("events", []) or []
    rounds: list[dict] = []

    for index, event in enumerate(events):
        if event.get("step") not in qa_steps or event.get("outcome") != "COMPLETED":
            continue
        qa_actor = (event.get("actor") or event.get("validator") or "").strip()
        producer_actor = ""
        producer_step = ""
        for earlier in reversed(events[:index]):
            if earlier.get("step") in qa_steps:
                continue
            if earlier.get("outcome") not in PRODUCER_OUTCOMES:
                continue
            producer_step = earlier.get("step", "")
            producer_actor = (earlier.get("actor") or "").strip()
            break

        if not qa_actor or not producer_actor:
            status = QA_ACTOR_UNKNOWN
        elif qa_actor == producer_actor:
            status = SELF_QA_VIOLATION
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

    for event in state.get("events", []) or []:
        step = event.get("step")
        if not step:
            continue
        if step not in by_step:
            order.append(step)
            by_step[step] = {"step": step, "producer_actor": "", "qa_actor": "",
                             "gate": "", "at": "", "qa_at": "", "state": NOT_SUBMITTED}
        row = by_step[step]
        role = event.get("role") or qa_policy.PRODUCER
        outcome = event.get("outcome") or ""

        if role == qa_policy.QA:
            if outcome == "FAILED":
                row["state"], row["qa_actor"] = "QA_FAILED", event.get("actor", "")
                row["qa_at"], row["gate"] = event.get("at", ""), event.get("gate", "") or row["gate"]
            elif outcome in ("PASS", "COMPLETED", "COMPLETED_WITH_CONTINUITY_CAVEAT",
                             "USABLE_WITH_SCENE_CONTINUITY_FAIL"):
                row["state"], row["qa_actor"] = "QA_PASSED", event.get("actor", "")
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
