import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from production_control import execution_contract, orchestrator, run_report, step_audit
from production_control.progress import append_event


CONSOLE = Path(__file__).resolve().parents[1]
MODEL = "gpt-5.6-luna"
QA_MODEL = "gpt-5.6-terra"


def _contract(project: Path, *, provider: str = "") -> dict:
    chain = json.loads((CONSOLE / "skills" / "skill-chain.json").read_text(encoding="utf-8"))
    contract = execution_contract.build_contract(
        chain=chain, project_root=project, run_id="RUN-TEST-A1", task_id="TEST-A1",
        segment="A1", version="v1", execution_model=MODEL, production_level="L1",
        image_assets_required=False, storyboard_required=False, provider=provider,
    )
    contract["current_step_id"] = "S08"
    contract["contract_id"] = "TEST-CONTRACT"
    return contract


def test_contract_requires_registered_model_and_existing_protocol(tmp_path):
    chain = json.loads((CONSOLE / "skills" / "skill-chain.json").read_text(encoding="utf-8"))
    with pytest.raises(execution_contract.ContractError, match="未登记执行模型"):
        execution_contract.build_contract(
            chain=chain, project_root=tmp_path, run_id="R", task_id="T", segment="A1",
            version="v1", execution_model="unknown-model", production_level="L1",
            image_assets_required=False, storyboard_required=False,
        )


def test_start_run_cli_persists_contract_in_isolated_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    result = subprocess.run(
        [sys.executable, str(CONSOLE / "tools" / "start_run.py"), str(project),
         "--run", "RUN-CLI-A1", "--segment", "A1", "--task-id", "CLI-A1",
         "--version", "v1", "--execution-model", MODEL, "--production-level", "L1",
         "--no-image-assets-required", "--no-storyboard-required"],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((project / "workflow" / "runs" / "RUN-CLI-A1.json").read_text(encoding="utf-8"))
    assert state["execution_contract"]["task_id"] == "CLI-A1"
    assert state["execution_contract"]["contract_id"] == "CLI-A1"
    assert state["execution_contract"]["qa_model"] == QA_MODEL
    assert state["execution_contract"]["provider_authorized"] is False
    assert "不会自动调用" in result.stdout
    schema = json.loads((CONSOLE / "schemas" / "run_state.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(state)


def test_contract_marks_conditional_steps_and_only_selected_adapter(tmp_path):
    contract = _contract(tmp_path, provider="libtv")
    by_id = {item["id"]: item for item in contract["steps"]}
    assert by_id["S06"]["disposition"] == "not_applicable"
    assert "无需新生" in by_id["S06"]["reason"]
    assert by_id["S07"]["applicable"] is True
    assert by_id["S07"]["mode"] == "key_state_only"
    assert by_id["S10"]["applicable"] is False
    assert by_id["S11"]["applicable"] is False
    assert by_id["S12"]["applicable"] is True
    assert contract["provider_authorized"] is False
    assert contract["qa_model"] == QA_MODEL
    assert contract["model_identity"] == "declared_unverified"


def test_isolated_run_submission_qa_and_board_audit_round_trip(tmp_path):
    contract = _contract(tmp_path)
    state = orchestrator.start(
        tmp_path / "unused.json", json.loads((CONSOLE / "skills" / "skill-chain.json").read_text(encoding="utf-8")),
        "RUN-TEST-A1", "TEST-CONTRACT", project_root=tmp_path,
        segment="A1", segment_title="测试段", contract=contract,
    )
    artifact = tmp_path / "prompt-v1.md"
    qa_report = tmp_path / "qa-v1.md"
    artifact.write_text("isolated artifact", encoding="utf-8")
    qa_report.write_text("isolated QA evidence", encoding="utf-8")
    common = dict(
        project_root=tmp_path, run_id="RUN-TEST-A1", step="S08", gate="G5",
        task_id="TEST-A1", version="v1", qa_level="C", affected_files=["prompt-v1.md"],
        protocol_refs=["12_真人短剧Prompt与故事本弹性标准_v3.0.md"],
    )
    append_event(
        **common, evidence="prompt-v1.md", outcome="SUBMITTED_FOR_QA", actor=MODEL,
        role="producer", writer_model=QA_MODEL,
    )
    after_submit = json.loads((tmp_path / "workflow" / "runs" / "RUN-TEST-A1.json").read_text(encoding="utf-8"))
    assert after_submit["execution_contract"]["current_owner"] == "qa"
    assert after_submit["execution_contract"]["steps"][7]["disposition"] == "submitted_for_qa"
    append_event(
        **common, evidence="qa-v1.md", outcome="COMPLETED", actor=QA_MODEL,
        role="qa", writer_model=QA_MODEL, qa_conclusion="PASS", elapsed_seconds=45,
        execution_model=MODEL, next_step="继续后续步骤", blocking_issues=[],
    )
    final_state = json.loads((tmp_path / "workflow" / "runs" / "RUN-TEST-A1.json").read_text(encoding="utf-8"))
    schema = json.loads((CONSOLE / "schemas" / "run_state.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(final_state)
    audit = step_audit.audit_qa_passes(final_state, tmp_path)
    assert audit["passed"] == 1
    assert audit["rows"][0]["state"] == step_audit.QA_PASSED
    declared_audit = step_audit.audit_steps(final_state, tmp_path)
    rows_by_step = {row["step_id"]: row for row in declared_audit["rows"] if row.get("step_id")}
    assert rows_by_step["S06"]["verdict"] == step_audit.NOT_APPLICABLE
    assert rows_by_step["S10"]["verdict"] == step_audit.NOT_APPLICABLE
    summary = run_report.summarize(final_state, project_root=tmp_path)
    assert summary["qa_passes"]["passed"] == 1

    forged = json.loads(json.dumps(final_state))
    qa_event = next(event for event in reversed(forged["events"]) if event.get("role") == "qa")
    qa_event["actor"] = MODEL
    qa_event["writer_model"] = MODEL
    assert step_audit.audit_qa_passes(forged, tmp_path)["passed"] == 0
    forged_rows = {row["step"]: row for row in step_audit.audit_steps(forged, tmp_path)["rows"]}
    assert forged_rows["short-drama-prompt-compiler"]["qa_passed"] is False


def test_contract_rejects_off_plan_events_and_mismatched_version(tmp_path):
    chain = json.loads((CONSOLE / "skills" / "skill-chain.json").read_text(encoding="utf-8"))
    contract = _contract(tmp_path)
    orchestrator.start(tmp_path / "unused.json", chain, "RUN-TEST-A1", "TEST-CONTRACT",
                       project_root=tmp_path, segment="A1", contract=contract)
    evidence = tmp_path / "evidence.md"
    evidence.write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="STEP_NOT_APPLICABLE"):
        append_event(tmp_path, "RUN-TEST-A1", step="S06", actor=MODEL, writer_model=QA_MODEL,
                     task_id="TEST-A1", version="v1", qa_level="C", evidence="evidence.md",
                     protocol_refs=["16_生图渠道规则_v3.0.md", "14_RH生图渠道与GPT通道现状_v3.0.md"])
    with pytest.raises(ValueError, match="EXECUTION_CONTRACT_MISMATCH"):
        append_event(tmp_path, "RUN-TEST-A1", step="S08", actor=MODEL, writer_model=QA_MODEL,
                     task_id="TEST-A1", version="v2", qa_level="C", evidence="evidence.md",
                     protocol_refs=["12_真人短剧Prompt与故事本弹性标准_v3.0.md"])


def test_contract_rejects_glm_writer_and_missing_evidence(tmp_path):
    chain = json.loads((CONSOLE / "skills" / "skill-chain.json").read_text(encoding="utf-8"))
    contract = _contract(tmp_path)
    orchestrator.start(tmp_path / "unused.json", chain, "RUN-TEST-A1", "TEST-CONTRACT",
                       project_root=tmp_path, segment="A1", contract=contract)
    args = dict(project_root=tmp_path, run_id="RUN-TEST-A1", step="S08", actor=MODEL,
                task_id="TEST-A1", version="v1", qa_level="C",
                protocol_refs=["12_真人短剧Prompt与故事本弹性标准_v3.0.md"])
    with pytest.raises(FileNotFoundError):
        append_event(**args, writer_model=QA_MODEL, evidence="missing.md")
    evidence = tmp_path / "evidence.md"
    evidence.write_text("test", encoding="utf-8")
    with pytest.raises(PermissionError, match="QA_WRITER_ROUTE_MISMATCH"):
        append_event(**args, writer_model="glm-5.3-flash", evidence="evidence.md")


def test_contract_rejects_skipping_ahead_of_current_step(tmp_path):
    chain = json.loads((CONSOLE / "skills" / "skill-chain.json").read_text(encoding="utf-8"))
    contract = execution_contract.build_contract(
        chain=chain, project_root=tmp_path, run_id="RUN-ORDER", task_id="ORDER",
        segment="A1", version="v1", execution_model=MODEL, production_level="L1",
        image_assets_required=False, storyboard_required=False,
    )
    orchestrator.start(tmp_path / "unused.json", chain, "RUN-ORDER", "ORDER",
                       project_root=tmp_path, segment="A1", contract=contract)
    evidence = tmp_path / "evidence.md"
    evidence.write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="STEP_OUT_OF_ORDER"):
        append_event(tmp_path, "RUN-ORDER", step="S08", actor=MODEL, writer_model=QA_MODEL,
                     task_id="ORDER", version="v1", qa_level="C", evidence="evidence.md",
                     protocol_refs=["12_真人短剧Prompt与故事本弹性标准_v3.0.md"])
