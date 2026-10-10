import hashlib
import json

from production_control import resume_run, run_index, task_state


def _run(tmp_path, *, task_id=None):
    root = tmp_path
    path = run_index.run_path(root, "RUN-RESUME")
    evidence = root / "workflow" / "evidence.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("confirmed script", encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    state = {
        "run_id": "RUN-RESUME", "contract_id": "TASK-1", "current_step": "short-drama-scene-continuity",
        "status": "RUNNING", "pipeline": [], "completed_steps": ["short-drama-production-router"],
        "events": [{"step": "short-drama-production-router", "step_id": "S01", "outcome": "STEP_COMPLETED",
                    "evidence": "workflow/evidence.md", "evidence_sha256": digest}],
        "execution_contract": {
            "run_id": "RUN-RESUME", "current_step_id": "S02", "current_owner": "producer",
            "protocol_root": str(tmp_path), "steps": [
                {"id": "S01", "display_id": "G0-S01", "skill": "short-drama-production-router",
                 "applicable": True, "disposition": "fact_recorded", "mode": ""},
                {"id": "S02", "display_id": "G2-S03", "skill": "short-drama-scene-continuity",
                 "applicable": True, "disposition": "pending", "mode": ""},
                {"id": "S12", "display_id": "G6-S12", "skill": "short-drama-task-monitor",
                 "applicable": True, "disposition": "pending", "mode": ""},
            ],
        },
    }
    if task_id:
        state["execution_contract"]["provider_task_id"] = task_id
    task_state.write_task(path, state)
    return path, evidence


def test_resume_reuses_hash_valid_evidence_and_keeps_next_pending_step(tmp_path, monkeypatch):
    monkeypatch.setattr(resume_run.protocol_versions, "check_current", lambda contract: [])
    path, _ = _run(tmp_path)
    result = resume_run.resume(tmp_path, "RUN-RESUME")
    assert result["current_step_id"] == "S02"
    state = task_state.read_task(path)
    assert state["execution_contract"]["current_step_id"] == "S02"
    assert len(state["events"]) == 1
    assert len(state["resume_history"]) == 1


def test_resume_rewinds_only_pointer_when_evidence_hash_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(resume_run.protocol_versions, "check_current", lambda contract: [])
    path, evidence = _run(tmp_path)
    evidence.write_text("changed under same path", encoding="utf-8")
    result = resume_run.resume(tmp_path, "RUN-RESUME")
    state = task_state.read_task(path)
    assert result["current_step_id"] == "S01"
    assert state["events"][0]["evidence_sha256"] != hashlib.sha256(evidence.read_bytes()).hexdigest()
    assert state["execution_contract"]["current_step_id"] == "S01"


def test_resume_queries_original_provider_task_without_new_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(resume_run.protocol_versions, "check_current", lambda contract: [])
    path, _ = _run(tmp_path, task_id="provider-task-123")
    result = resume_run.resume(tmp_path, "RUN-RESUME")
    state = task_state.read_task(path)
    assert result["current_step_id"] == "S12"
    assert state["execution_contract"]["current_step_id"] == "S12"
    assert state["execution_contract"]["provider_task_id"] == "provider-task-123"
    assert len(state["events"]) == 1


def test_resume_reports_verified_provider_terminal_without_reopening_run(tmp_path, monkeypatch):
    path, _ = _run(tmp_path, task_id="provider-task-123")
    state = task_state.read_task(path)
    state["events"].append({"step_id": "S12", "outcome": "TASK_SUCCEEDED",
                            "provider_task_id": "provider-task-123", "provider_status": "SUCCESS",
                            "output_urls": ["https://provider.invalid/video.mp4"]})
    state["status"] = "COMPLETED"
    task_state.write_task(path, state)
    result = resume_run.resume(tmp_path, "RUN-RESUME")
    after = task_state.read_task(path)
    assert result["status"] == "COMPLETED"
    assert result["output_urls"] == ["https://provider.invalid/video.mp4"]
    assert after["status"] == "COMPLETED"
    assert "resume_history" not in after


def test_resume_does_not_advance_while_waiting_for_user(tmp_path, monkeypatch):
    path, _ = _run(tmp_path)
    state = task_state.read_task(path)
    state["status"] = "WAITING_APPROVAL"
    state["pending_decision"] = "需要确认脚本改动"
    state["execution_contract"]["current_owner"] = "user"
    task_state.write_task(path, state)
    result = resume_run.resume(tmp_path, "RUN-RESUME")
    after = task_state.read_task(path)
    assert result["status"] == "WAITING_DECISION"
    assert after["execution_contract"]["current_step_id"] == "S02"
    assert "resume_history" not in after


def test_asset_index_v2_requires_confirmation_metadata():
    from production_control.asset_registry import validate_registry

    sample = json.loads((__import__("pathlib").Path(__file__).parents[1] / "examples" / "asset_index.example.json").read_text(encoding="utf-8"))
    assert validate_registry(sample) == []
    del sample["assets"][0]["confirmation_evidence"]
    assert any("confirmation_evidence" in error for error in validate_registry(sample))
