import json

from production_control import orchestrator, protocol_fingerprint


def test_invalid_skill_audit_blocks_before_submit_and_preserves_run_counters(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "APPROVAL_BREAKPOINTS", {})
    monkeypatch.setattr(orchestrator.step_registry, "by_id",
                        lambda step_id: type("Step", (), {"skill": "short-drama-authorized-submit"})()
                        if step_id == "S11" else None)
    monkeypatch.setattr("production_control.protocol_versions.check_current", lambda contract: [])
    audit_dir = tmp_path / "workflow" / "skill_audits"
    audit_dir.mkdir(parents=True)
    (audit_dir / "TASK-7_skill_audit.json").write_text(json.dumps({
        "unit_id": "TASK-7", "model": "Seedance 2.5", "overall": "PASS",
        "skills": [{"id": "seedance-shot-design", "status": "INVALID"}],
        "errors": ["invalid status"], "codes": [],
    }), encoding="utf-8")
    called = []
    state = {
        "run_id": "RUN-7", "project_root": str(tmp_path), "pipeline": ["short-drama-authorized-submit"],
        "status": "RUNNING", "completed_steps": [], "events": [], "budget_used": 3,
        "execution_contract": {"task_id": "TASK-7", "current_step_id": "S11", "current_owner": "executor",
                               "selected_provider": "libtv", "submission_count": 1},
    }
    result = orchestrator._advance(state, {"short-drama-authorized-submit": lambda: called.append(True)})
    assert result["status"] == "PAUSED_EXCEPTION"
    assert "SKILL_GATE_BLOCKED" in result["pending_decision"]
    assert called == []
    assert result["budget_used"] == 3
    assert result["execution_contract"]["submission_count"] == 1


def test_g6_submit_step_pins_skill_audit_protocol():
    entry = orchestrator.step_registry.by_id("S11")
    assert "21_G5.1模型Skill审计与Prompt版本规则_v3.0.md" in entry.protocol_refs
    assert "21_G5.1模型Skill审计与Prompt版本规则_v3.0.md" in protocol_fingerprint.registered_protocol_files()
