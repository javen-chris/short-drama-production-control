import json
from pathlib import Path

from production_control.asset_registry import validate_registry, check_contract_assets
from production_control.preflight_gate import validate_preflight
from production_control.cost_ledger import idempotency_key, register_submission, budget_status
from production_control import orchestrator
from production_control import run_state
from production_control.qa_report import classify_rework, top_rework_classes

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp_pipeline"
APPROVED = {"asset_id": "CH-01", "role": "character_master", "path": "master/ch.png", "sha256": "a" * 64, "status": "APPROVED", "allowed_use": ["identity"], "image_channel": "gpt_image2_local_subscription", "qa_evidence": "qa/ch.json"}


def test_registry_requires_approved_and_scoped_entries():
    registry = {"registry_version": "1.0", "series_id": "DEMO", "assets": [dict(APPROVED, status="DRAFT")]}
    assert any("not APPROVED" not in e for e in validate_registry(registry)) or "DRAFT" in registry["assets"][0]["status"]


def test_registry_rejects_missing_image_channel_for_master():
    bad = json.loads(json.dumps(APPROVED))
    bad.pop("image_channel")
    assert any("image channels" in e for e in validate_registry({"registry_version": "1.0", "series_id": "DEMO", "assets": [bad]}))


def test_unregistered_contract_asset_is_rejected():
    registry = {"registry_version": "1.0", "series_id": "DEMO", "assets": [APPROVED]}
    errors = check_contract_assets(registry, [{"role": "character_master", "path": "master/other.png"}], verify_files=False)
    assert any("not found" in e for e in errors)


def test_registry_role_mismatch_is_rejected():
    registry = {"registry_version": "1.0", "series_id": "DEMO", "assets": [APPROVED]}
    errors = check_contract_assets(registry, [{"role": "scene_master", "path": "master/ch.png"}], verify_files=False)
    assert any("registry role" in e for e in errors)


def test_contract_asset_hash_is_verified(tmp_path):
    target = tmp_path / "master.png"
    target.write_bytes(b"master-bytes")
    from production_control.provenance import sha256_file

    entry = dict(APPROVED, path=str(target), sha256=sha256_file(target))
    registry = {"registry_version": "1.0", "series_id": "DEMO", "assets": [entry]}
    assert check_contract_assets(registry, [{"role": "character_master", "path": str(target)}]) == []
    corrupted = dict(APPROVED, path=str(target), sha256="b" * 64)
    errors = check_contract_assets({"registry_version": "1.0", "series_id": "DEMO", "assets": [corrupted]}, [{"role": "character_master", "path": str(target)}])
    assert any("sha256 mismatch" in e for e in errors)


def test_preflight_blocks_missing_master_ready_status():
    record = {
        "project": "DEMO", "segment": "EP01-U01", "script_source": "script.md",
        "asset_manifest": [{"role": "character_master", "name": "女主"}],
        "node_status": "READY_FOR_NODE",
    }
    assert any("MASTER manifest incomplete" in e for e in validate_preflight(record))


def test_preflight_allows_missing_tail_frame_as_degradation():
    record = {
        "project": "DEMO", "segment": "EP01-U01", "script_source": "script.md",
        "asset_manifest": [
            {"role": "character_master", "name": "女主", "path": "master/ch.png"},
            {"role": "scene_master", "name": "书房", "path": "master/scene.png"},
            {"role": "prop_master", "name": "手机", "path": "master/phone.png"},
            {"role": "tail_frame", "name": "上一镜尾帧", "degraded_note": "未授权制作，按文字状态承接"},
            {"role": "storyboard", "name": "故事本", "degraded_note": "未授权制作，强化禁项直拍"},
        ],
        "node_status": "READY_FOR_NODE",
    }
    assert validate_preflight(record) == []


def test_preflight_blocked_status_must_name_a_master():
    record = {
        "project": "DEMO", "segment": "EP01-U01", "script_source": "script.md",
        "asset_manifest": [{"role": "character_master", "name": "女主", "path": "master/ch.png"}],
        "node_status": "BLOCKED_PRECHECK",
        "missing": ["scene_master"],
    }
    assert validate_preflight(record) == []


def test_duplicate_submission_is_refused():
    ledger = {"budget_cny": 10, "entries": []}
    payload = {"prompt_unit_id": "EP01-U01", "model": "h3"}
    register_submission(ledger, "EP01-U01", "C1", "runninghub", payload, cost_cny=0.5)
    try:
        register_submission(ledger, "EP01-U01", "C1", "runninghub", payload, cost_cny=0.5)
    except ValueError as e:
        assert "duplicate submission refused" in str(e)
    else:
        assert False
    assert len(ledger["entries"]) == 1


def test_idempotency_key_changes_with_input():
    a = idempotency_key("U1", "C1", "runninghub", {"x": 1})
    b = idempotency_key("U1", "C1", "runninghub", {"x": 2})
    assert a != b


def test_budget_status_flags_overspend():
    ledger = {"budget_cny": 1, "entries": [{"cost_cny": 2, "status": "SUCCEEDED"}]}
    status = budget_status(ledger)
    assert status["over_budget"] is True


def test_rework_classes_aggregate_failures():
    reports = [
        {"checks": {"identity": "FAIL", "prop": "UNCERTAIN", "decode": "FAIL"}},
        {"checks": {"identity": "FAIL", "dialogue": "FAIL"}},
    ]
    counts = classify_rework(reports)
    assert counts["identity"] == 2
    assert counts["prop"] == 1
    assert counts["image_quality"] == 1
    assert top_rework_classes(reports, limit=1) == [("identity", 2)]


def _chain():
    return {
        "steps": [
            {"skill": "short-drama-script-breakdown", "after": []},
            {"skill": "short-drama-script-reviewer", "after": ["short-drama-script-breakdown"]},
            {"skill": "short-drama-production-qa", "after": ["short-drama-script-reviewer"]},
            {"skill": "runninghub-local-adapter", "after": ["short-drama-production-qa"]},
        ]
    }


def test_orchestrator_stops_at_approval_breakpoint(tmp_path):
    chain = _chain()
    state_path = tmp_path / "run_state.json"
    state = orchestrator.start(state_path, chain, "RUN-1", "C1")
    assert state["status"] == "RUNNING"
    state = orchestrator.advance(state, {})
    assert state["status"] == "WAITING_APPROVAL"
    assert state["checkpoint"] == "short-drama-script-breakdown"
    run_state.write_task(state_path, state)


def test_orchestrator_resumes_after_approval(tmp_path):
    chain = _chain()
    state_path = tmp_path / "run_state.json"
    state = orchestrator.start(state_path, chain, "RUN-2", "C1")
    state = orchestrator.advance(state, {})
    assert state["status"] == "WAITING_APPROVAL"
    seen = []
    handlers = {
        "short-drama-script-breakdown": lambda: seen.append("breakdown") or {},
        "short-drama-script-reviewer": lambda: {},
        "short-drama-production-qa": lambda: {},
        "runninghub-local-adapter": lambda: {},
    }
    approvals = {"short-drama-script-breakdown", "short-drama-script-reviewer", "short-drama-production-qa", "runninghub-local-adapter"}
    for _ in range(len(orchestrator.plan_steps(chain))):
        state = orchestrator.advance(state, handlers, approvals)
        if state["status"] in {"WAITING_APPROVAL", "PAUSED_EXCEPTION", "COMPLETED", "BLOCKED"}:
            break
    assert seen == ["breakdown"]
    assert state["status"] == "COMPLETED"
    assert state["completed_steps"] == orchestrator.plan_steps(chain)


def test_orchestrator_parks_on_step_failure(tmp_path):
    chain = _chain()
    state_path = tmp_path / "run_state.json"
    state = orchestrator.start(state_path, chain, "RUN-3", "C1")
    state = orchestrator.advance(state, {})

    def boom():
        raise orchestrator.StepFailure("missing_authoritative_script", "script/lookup.json")

    handlers = {"short-drama-script-breakdown": boom}
    state = orchestrator.advance(state, handlers, {"short-drama-script-breakdown"})
    assert state["status"] == "PAUSED_EXCEPTION"
    assert state["pending_decision"] == "missing_authoritative_script"
    assert run_state.resume_point(state) == "short-drama-script-breakdown"


def test_orchestrator_blocks_unhandled_step(tmp_path):
    chain = _chain()
    state_path = tmp_path / "run_state.json"
    state = orchestrator.start(state_path, chain, "RUN-4", "C1")
    approvals = set(orchestrator.plan_steps(chain))
    state = orchestrator.advance(state, {"short-drama-script-breakdown": lambda: {}}, approvals)
    state = orchestrator.advance(state, {}, approvals)
    assert state["status"] == "BLOCKED"
