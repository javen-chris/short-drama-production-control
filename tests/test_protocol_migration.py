import json
import subprocess
import sys
from pathlib import Path


def test_protocol_migration_updates_same_run_and_preserves_history(tmp_path):
    console = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    runs = project / "workflow" / "runs"
    runs.mkdir(parents=True)
    old_attestation = {"status": "PASS", "attestation_id": "OLD", "manifest_fingerprint": "b" * 64}
    state = {
        "run_id": "RUN-MIGRATE-1", "contract_id": "CONTRACT-1", "current_step": "short-drama-prompt-compiler",
        "status": "RUNNING", "pipeline": ["short-drama-prompt-compiler"], "completed_steps": [],
        "events": [{"step": "short-drama-script-breakdown", "outcome": "STEP_COMPLETED", "evidence": "script.md"}],
        "protocol_attestation": old_attestation, "protocol_attestations": [old_attestation],
        "execution_contract": {
            "contract_id": "CONTRACT-1", "task_id": "TASK-1", "protocol_root": r"D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议",
            "protocol_manifest_fingerprint": "b" * 64, "current_step_id": "S08",
            "steps": [{"id": "S08", "applicable": False, "protocol_refs": []}],
            "submission_count": 1, "budget_cny": 25,
        },
    }
    run_path = runs / "RUN-MIGRATE-1.json"
    run_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    from production_control import protocol_fingerprint
    evidence = project / "confirmed_changes.md"
    evidence.write_text("Isolated test explicit protocol migration confirmation", encoding="utf-8")
    confirmed = ["--confirmation-evidence", "confirmed_changes.md"]
    for rel in protocol_fingerprint.REQUIRED_CORE_FILES + protocol_fingerprint.RUNTIME_CONTROL_FILES:
        confirmed.extend(["--confirmed-path", rel])
    result = subprocess.run(
        [sys.executable, str(console / "tools" / "migrate_run_protocol.py"), str(project), "--run", "RUN-MIGRATE-1", *confirmed],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    migrated = json.loads(run_path.read_text(encoding="utf-8"))
    assert migrated["run_id"] == state["run_id"]
    assert len(migrated["events"]) == len(state["events"])
    assert migrated["execution_contract"]["submission_count"] == 1
    assert migrated["execution_contract"]["budget_cny"] == 25
    assert migrated["protocol_attestations"] == [old_attestation]
    assert migrated["protocol_migrations"][0]["preserved_event_count"] == 1
    assert migrated["execution_contract"]["protocol_manifest_fingerprint"] != "b" * 64
