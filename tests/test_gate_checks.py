"""Historical auxiliary activity must surface without forging protocol progress."""
import json

from production_control import gate_checks, step_registry
from production_control.run_report import render_html, summarize
from production_control.skill_chain_validator import validate_chain


def test_all_ep03_legacy_activity_has_one_interpretation():
    definitions = gate_checks.definitions()
    names = [name for row in definitions for name in row["activity_names"]]
    assert len(names) == len(set(names)) == 17
    assert "protocol-attestation" not in names
    assert step_registry.resolve("protocol-attestation").step.marker
    assert all(row["gate"] in {"G3", "G5", "G6"} for row in definitions)
    assert all(row["id"] and row["name_zh"] and row["protocol_refs"] for row in definitions)
    assert all(row["purpose_zh"] and row["decision_zh"] for row in definitions)
    assert all(row["counts_as_step_progress"] is False for row in definitions)


def test_latest_scope_change_does_not_turn_old_node_failure_into_a_pass():
    rows = [
        {"step": "g6-stale-node-readback", "verdict": "EXTRA", "outcome": "BLOCKED",
         "at": "2026-09-25T16:14:09+08:00"},
        {"step": "g6-main-unit-only-correction", "verdict": "EXTRA",
         "outcome": "SUBMITTED_FOR_QA", "at": "2026-09-25T16:48:10+08:00"},
        {"step": "g6-compliance-resourceid-diagnosis", "verdict": "EXTRA",
         "outcome": "BLOCKED", "at": "2026-09-25T16:26:49+08:00"},
        {"step": "a-new-unknown-action", "verdict": "EXTRA", "outcome": "BLOCKED", "at": ""},
    ]
    checks, handled = gate_checks.classify(rows)
    by_id = {row["id"]: row for row in checks}
    assert by_id["C63"]["status"] == "warn"
    assert by_id["C66"]["status"] == "bad"
    assert "a-new-unknown-action" not in handled


def test_check_events_affect_gate_warning_but_never_step_progress():
    state = {
        "run_id": "R1", "pipeline": [], "completed_steps": [],
        "events": [{"step": "seedance-skill-audit", "outcome": "BLOCKED",
                    "at": "2026-09-25T00:00:00Z", "evidence": "qa/skill.md"}],
    }
    summary = summarize(state)
    html = render_html(summary)
    assert summary["progress"] == {"completed": 0, "total": 0}
    assert "G5.1 Skill 与 Prompt 版本审计" in html
    assert 'data-gate="G5"' in html
    assert "有阻断" in html
    assert "辅助审计记录" in html
    assert "确认当前 Prompt 版本确实经过对应 Skill" in html


def test_registry_gate_checks_reject_duplicate_activity_names_in_guard(tmp_path):
    # Deliberately inject a bad alias: a one-name-to-two-check mapping is unsafe.
    data = json.loads((step_registry.repo_root() / step_registry.CHAIN_RELPATH).read_text(encoding="utf-8"))
    names = [name for row in data["gate_checks"] for name in row["activity_names"]]
    assert len(names) == len(set(names))
    data["gate_checks"][1]["activity_names"].append(data["gate_checks"][0]["activity_names"][0])
    broken = tmp_path / "skill-chain.json"
    broken.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert any("duplicate activity mapping" in error for error in validate_chain(broken))
