import copy

from production_control import orchestrator
from production_control import run_state
from production_control.run_compliance import (
    STEP_PROTOCOL_REQUIREMENTS,
    compliance_gaps,
    verify_run_compliance,
)

CHAIN = {
    "steps": [
        {"skill": "short-drama-script-breakdown", "after": []},
        {"skill": "short-drama-script-reviewer", "after": ["short-drama-script-breakdown"]},
        {"skill": "short-drama-image-generator", "after": ["short-drama-script-reviewer"]},
        {"skill": "short-drama-production-qa", "after": ["short-drama-image-generator"]},
    ]
}

REFS_BREAKDOWN = [{"path": "09_脚本优化与分镜拆解规范_v3.0.md"}]
REFS_REVIEWER = [{"path": "09_脚本优化与分镜拆解规范_v3.0.md"}]
REFS_IMAGE = [{"path": "16_生图渠道规则_v3.0.md"}, {"path": "14_RH生图渠道与GPT通道现状_v3.0.md"}]
REFS_QA = [{"path": "04_QA与文件治理_v3.0.md"}]


def _result(step, refs, **extra):
    payload = {"skill_id": step, "protocol_refs": refs, "evidence": f"evidence/{step}.json"}
    payload.update(extra)
    return payload


def _handlers():
    return {
        "short-drama-script-breakdown": lambda: _result("short-drama-script-breakdown", REFS_BREAKDOWN),
        "short-drama-script-reviewer": lambda: _result("short-drama-script-reviewer", REFS_REVIEWER),
        "short-drama-image-generator": lambda: _result("short-drama-image-generator", REFS_IMAGE),
        "short-drama-production-qa": lambda: _result("short-drama-production-qa", REFS_QA),
    }


def _run(state_path, handlers, approvals, steps=4):
    state = orchestrator.start(state_path, CHAIN, "RUN-C", "C1")
    for _ in range(steps):
        state = orchestrator.advance(state, handlers, approvals)
        if state["status"] in {"PAUSED_EXCEPTION", "BLOCKED", "COMPLETED"}:
            break
    return state


def test_fully_documented_run_is_compliant(tmp_path):
    state = _run(tmp_path / "run.json", _handlers(), set(orchestrator.plan_steps(CHAIN)))
    assert state["status"] == "COMPLETED"
    result = verify_run_compliance(state, CHAIN)
    assert result["errors"] == []
    assert result["status"] == "PASS"


def test_step_without_protocol_refs_is_not_completed(tmp_path):
    handlers = _handlers()
    handlers["short-drama-image-generator"] = lambda: {"skill_id": "short-drama-image-generator", "evidence": "e.json"}
    approvals = set(orchestrator.plan_steps(CHAIN))
    state = _run(tmp_path / "run.json", handlers, approvals)
    assert state["status"] == "PAUSED_EXCEPTION"
    assert "protocol_refs" in state["pending_decision"]
    assert "short-drama-image-generator" not in state["completed_steps"]


def test_skill_id_mismatch_is_rejected(tmp_path):
    handlers = _handlers()
    handlers["short-drama-script-reviewer"] = lambda: _result("short-drama-script-breakdown", REFS_REVIEWER)
    approvals = set(orchestrator.plan_steps(CHAIN))
    state = _run(tmp_path / "run.json", handlers, approvals)
    assert state["status"] == "PAUSED_EXCEPTION"
    assert "does not match step" in state["pending_decision"]


def test_missing_required_protocol_read_is_a_named_gap(tmp_path):
    state = _run(tmp_path / "run.json", _handlers(), set(orchestrator.plan_steps(CHAIN)))
    tampered = copy.deepcopy(state)
    for event in tampered["events"]:
        if event["step"] == "short-drama-image-generator":
            event["protocol_refs"] = [{"path": "16_生图渠道规则_v3.0.md"}]
    gaps = compliance_gaps(tampered, CHAIN)
    assert any("did not record reading 14_RH生图渠道与GPT通道现状_v3.0.md" in g for g in gaps)


def test_stale_protocol_hash_is_reported(tmp_path):
    state = _run(tmp_path / "run.json", _handlers(), set(orchestrator.plan_steps(CHAIN)))
    manifest = {"files": [{"path": "16_生图渠道规则_v3.0.md", "sha256": "a" * 64}]}
    tampered = copy.deepcopy(state)
    for event in tampered["events"]:
        if event["step"] == "short-drama-image-generator":
            event["protocol_refs"] = [
                {"path": "16_生图渠道规则_v3.0.md", "sha256": "b" * 64},
                {"path": "14_RH生图渠道与GPT通道现状_v3.0.md"},
            ]
    result = verify_run_compliance(tampered, CHAIN, manifest)
    assert any("hash does not match" in e for e in result["errors"])


def test_every_chain_step_has_declared_protocol_requirements():
    chain = {
        "steps": [
            {"skill": "short-drama-script-breakdown", "after": []},
            {"skill": "short-drama-image-generator", "after": []},
            {"skill": "short-drama-production-qa", "after": []},
            {"skill": "runninghub-local-adapter", "after": []},
        ]
    }
    for step in orchestrator.plan_steps(chain):
        assert STEP_PROTOCOL_REQUIREMENTS.get(step), f"{step} has no declared protocol requirement"
