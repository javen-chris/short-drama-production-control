"""Fail-closed Skill audit tests: status, routing, evidence and caller behavior."""
import hashlib
import json

from production_control import skill_audit as sa


def _fixture(tmp_path, model="Seedance 2.5", skills=None):
    (tmp_path / "workflow").mkdir(parents=True, exist_ok=True)
    mode = "I2VA" if model == "rh_h3" else "I2V"
    prompt = {**{k: "ok" for k in sa.REQUIRED_PROMPT_SECTIONS}, "unit_id": "U01", "mode": mode}
    (tmp_path / "prompt.json").write_text(json.dumps(prompt), encoding="utf-8")
    (tmp_path / "source.txt").write_text("confirmed script", encoding="utf-8")
    contract = {"unit_id": "U01", "model": model, "model_version": "v2"}
    (tmp_path / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
    audit = {"unit_id": "U01", "model": model, "model_version": "v2", "mode": mode,
             "contract_path": "contract.json", "prompt_path": "prompt.json",
             "prompt_sha256": hashlib.sha256((tmp_path / "prompt.json").read_bytes()).hexdigest(),
             "input_hashes": {"source.txt": hashlib.sha256(b"confirmed script").hexdigest()},
             "prompt_id": "P01", "prompt_version": "v1", "overall": "PASS", "skills": []}
    audit["skills"] = skills if skills is not None else ["seedance-shot-design"]
    for sid in audit["skills"]:
        record = {"unit_id": "U01", "skill_id": sid, "model": model, "model_version": "v2",
                  "mode": mode, "prompt_sha256": audit["prompt_sha256"],
                  "input_hashes": audit["input_hashes"], "status": "PASS"}
        evidence_path = tmp_path / f"{sid}.json"
        evidence_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        sid_obj = {"id": sid, "version": "local", "status": "PASS",
                   "evidence": {"path": f"{sid}.json", "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest()}}
        audit["skills"][audit["skills"].index(sid)] = sid_obj
    return audit


def test_valid_matching_skill_and_bound_evidence_pass(tmp_path):
    audit = _fixture(tmp_path)
    verdict = sa.evaluate(audit, tmp_path)
    assert verdict["ok"] is True and verdict["overall"] == "PASS"


def test_model_routing_for_h3_and_seedance_versions(tmp_path):
    cases = [("rh_h3", ["h3-prompt-writing"]),
             ("Seedance 2.5", ["seedance-shot-design"]),
             ("seedance_2.0", ["seedance-20", "seedance-prompt"])]
    for model, skills in cases:
        audit = _fixture(tmp_path / model.replace("/", "_"), model=model, skills=skills)
        assert sa.evaluate(audit, tmp_path / model.replace("/", "_"))["ok"]


def test_invalid_or_missing_status_and_nonpass_states_block(tmp_path):
    for status in (None, "", "INVALID", "FAIL", "UNCERTAIN", "NOT_RUN"):
        audit = _fixture(tmp_path / str(status), skills=["seedance-shot-design"])
        audit["skills"][0]["status"] = status
        verdict = sa.evaluate(audit, tmp_path / str(status))
        assert not verdict["ok"] and verdict["overall"] != "PASS"
        assert verdict["errors"] and verdict["codes"]
        assert ("SKILL_STATUS_INVALID" in verdict["codes"]) if status in (None, "", "INVALID") else True


def test_empty_skill_list_blocks(tmp_path):
    audit = _fixture(tmp_path, skills=[])
    verdict = sa.evaluate(audit, tmp_path)
    assert not verdict["ok"] and "SKILL_NOT_RUN" in verdict["codes"]


def test_irrelevant_skill_unknown_model_and_contract_mismatch_block(tmp_path):
    audit = _fixture(tmp_path, skills=["seedance-prompt"])
    verdict = sa.evaluate(audit, tmp_path)
    assert not verdict["ok"] and "SKILL_REQUIRED_MISSING" in verdict["codes"]
    audit = _fixture(tmp_path / "foreign", skills=["seedance-shot-design", "h3-prompt-writing"])
    assert "SKILL_MODEL_MISMATCH" in sa.evaluate(audit, tmp_path / "foreign")["codes"]
    audit = _fixture(tmp_path / "unknown", model="Seedance latest", skills=["seedance-shot-design"])
    assert "SKILL_MODEL_UNKNOWN" in sa.evaluate(audit, tmp_path / "unknown")["codes"]
    audit = _fixture(tmp_path / "mismatch", skills=["seedance-shot-design"])
    (tmp_path / "mismatch" / "contract.json").write_text(json.dumps({"unit_id": "U01", "model": "rh_h3", "model_version": "v2"}), encoding="utf-8")
    assert "SKILL_MODEL_MISMATCH" in sa.evaluate(audit, tmp_path / "mismatch")["codes"]


def test_mode_must_be_supported_by_selected_model(tmp_path):
    audit = _fixture(tmp_path)
    audit["mode"] = "T2VA"
    assert "SKILL_INPUT_MISMATCH" in sa.evaluate(audit, tmp_path)["codes"]


def test_missing_unreadable_or_wrong_digest_evidence_blocks(tmp_path):
    for kind in ("missing", "unreadable", "digest"):
        audit = _fixture(tmp_path / kind)
        evidence = audit["skills"][0]["evidence"]
        if kind == "missing":
            evidence["path"] = "does-not-exist.json"
        elif kind == "unreadable":
            (tmp_path / kind / "seedance-shot-design.json").write_text("{", encoding="utf-8")
        else:
            evidence["sha256"] = "0" * 64
        assert not sa.evaluate(audit, tmp_path / kind)["ok"]


def test_prompt_edit_cannot_be_bypassed_by_renaming_version(tmp_path):
    audit = _fixture(tmp_path)
    prompt_file = tmp_path / "prompt.json"
    prompt = json.loads(prompt_file.read_text(encoding="utf-8"))
    prompt["primary_action"] = "materially changed"
    prompt_file.write_text(json.dumps(prompt), encoding="utf-8")
    audit["prompt_version"] = "v999"
    verdict = sa.evaluate(audit, tmp_path)
    assert not verdict["ok"] and "PROMPT_CONTENT_MISMATCH" in verdict["codes"]


def test_markdown_prompt_is_hashed_as_raw_content(tmp_path):
    audit = _fixture(tmp_path)
    markdown = tmp_path / "prompt.md"
    markdown.write_text("# U01\n模式：I2V\n动作：向前转身", encoding="utf-8")
    audit["prompt_path"] = "prompt.md"
    audit["prompt_sha256"] = hashlib.sha256(markdown.read_bytes()).hexdigest()
    for item in audit["skills"]:
        record = json.loads((tmp_path / item["evidence"]["path"]).read_text(encoding="utf-8"))
        record["prompt_sha256"] = audit["prompt_sha256"]
        evidence_path = tmp_path / item["evidence"]["path"]
        evidence_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        item["evidence"]["sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    assert sa.evaluate(audit, tmp_path)["ok"]


def test_input_hash_and_evidence_bindings_are_checked(tmp_path):
    audit = _fixture(tmp_path)
    (tmp_path / "source.txt").write_text("changed", encoding="utf-8")
    assert "SKILL_INPUT_MISMATCH" in sa.evaluate(audit, tmp_path)["codes"]
    audit = _fixture(tmp_path / "evidence", skills=["seedance-shot-design"])
    evidence_path = tmp_path / "evidence" / "seedance-shot-design.json"
    record = json.loads(evidence_path.read_text(encoding="utf-8"))
    record["unit_id"] = "OTHER"
    evidence_path.write_text(json.dumps(record), encoding="utf-8")
    audit["skills"][0]["evidence"]["sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    assert "SKILL_EVIDENCE_INVALID" in sa.evaluate(audit, tmp_path / "evidence")["codes"]
    audit = _fixture(tmp_path / "wrong-unit")
    assert "SKILL_INPUT_MISMATCH" in sa.evaluate(audit, tmp_path / "wrong-unit", "OTHER-UNIT")["codes"]


def test_node_caller_rejects_ok_true_when_audit_has_errors_or_codes():
    prompt = {key: "x" for key in sa.REQUIRED_PROMPT_SECTIONS}
    prompt["mode"] = "I2V"
    node = {"platform_node_status": "CREATED", "audit": {"mode": "I2V"}}
    for verdict in ({"ok": True, "overall": "PASS", "errors": ["bad"], "codes": []},
                    {"ok": True, "overall": "PASS", "errors": [], "codes": ["BLOCK"]},
                    {"ok": True, "overall": "SKILL_GATE_BLOCKED", "errors": [], "codes": []}):
        result = sa.node_readiness(verdict, {"overall": "PASS", "errors": [], "codes": []}, True, node, prompt)
        assert not result["ready"] and result["production_readiness"] == "FAIL"


def test_skill_execution_does_not_replace_independent_content_qa():
    prompt = {key: "x" for key in sa.REQUIRED_PROMPT_SECTIONS}
    prompt["mode"] = "I2V"
    node = {"platform_node_status": "CREATED", "prompt_version": "v1", "model": "Seedance 2.5",
            "modeType": "I2V", "audit": {"prompt_version": "v1", "model": "Seedance 2.5", "mode": "I2V"}}
    skill_pass = {"ok": True, "overall": "PASS", "errors": [], "codes": [], "model": "Seedance 2.5"}
    result = sa.node_readiness(skill_pass, {"overall": "NOT_RUN"}, True, node, prompt)
    assert not result["ready"] and "INDEPENDENT_QA_REQUIRED" in result["codes"]
    qa_pass = {"overall": "PASS", "errors": [], "codes": []}
    assert sa.node_readiness(skill_pass, qa_pass, True, node, prompt)["ready"]


def test_h3_uses_h3_prompt_shape_not_seedance_sections():
    assert sa.check_prompt_sections({"unit_id": "U01", "mode": "I2VA"}, "rh_h3") == []


def test_audit_overall_errors_and_codes_cannot_claim_pass(tmp_path):
    audit = _fixture(tmp_path)
    for field, value in (("overall", "FAIL"), ("errors", ["prior failure"]), ("codes", ["BLOCK"])):
        bad = dict(audit)
        bad[field] = value
        verdict = sa.evaluate(bad, tmp_path)
        assert not verdict["ok"] and verdict["errors"] and verdict["codes"]


def test_auditing_v1_does_not_clear_a_v2_node():
    problems = sa.check_node_binding({"prompt_version": "v1", "model": "Seedance 2.5"},
                                     {"prompt_version": "v2", "model": "Seedance 2.5"})
    assert problems
