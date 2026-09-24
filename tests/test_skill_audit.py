"""G5.1 exists because a batch of unusable prompts reached node creation.

The test that matters is the one asserting NOT_RUN blocks: "we will audit it
after we build the node" is the exact failure this gate is for.
"""
from production_control import skill_audit


def _audit(skills):
    return {"unit_id": "EP03_A1_15s", "model": "Seedance 2.5", "prompt_id": "P_v2",
            "prompt_version": "v2", "skill_audit_id": "SKILL_AUDIT_EP03_A1_v2",
            "skills": skills}


def _skill(sid, status="PASS", evidence="evidence://ok"):
    return {"id": sid, "version": "6.6.0", "status": status, "evidence": evidence}


def test_all_pass_grants_the_gate():
    verdict = skill_audit.evaluate(_audit([_skill(s) for s in
                                           ("seedance-prompt", "seedance-camera", "seedance-motion",
                                            "seedance-characters", "seedance-antislop")]))
    assert verdict["ok"] and verdict["overall"] == "PASS"


def test_not_run_blocks_and_may_not_be_deferred():
    verdict = skill_audit.evaluate(_audit([_skill("seedance-prompt"),
                                           _skill("seedance-antislop", status="NOT_RUN")]))
    assert not verdict["ok"]
    assert verdict["overall"] == "SKILL_GATE_BLOCKED"
    assert "SKILL_NOT_RUN" in verdict["codes"]


def test_uncertain_is_not_a_pass():
    verdict = skill_audit.evaluate(_audit([_skill("seedance-motion", status="UNCERTAIN")]))
    assert not verdict["ok"] and "SKILL_GATE_FAIL" in verdict["codes"]


def test_a_pass_without_evidence_counts_as_not_run():
    verdict = skill_audit.evaluate(_audit([_skill("seedance-camera", evidence="")]))
    assert not verdict["ok"] and "SKILL_EVIDENCE_MISSING" in verdict["codes"]


def test_an_empty_skill_list_means_the_gate_never_ran():
    verdict = skill_audit.evaluate({"unit_id": "A1", "skills": []})
    assert not verdict["ok"] and "SKILL_NOT_RUN" in verdict["codes"]


def test_prompt_must_carry_all_fifteen_sections():
    full = {section: "x" for section in skill_audit.REQUIRED_PROMPT_SECTIONS}
    assert skill_audit.check_prompt_sections(full) == []
    partial = dict(full)
    del partial["timeline"]
    assert skill_audit.check_prompt_sections(partial) == ["timeline"]


def test_auditing_v1_does_not_clear_a_v2_node():
    audit = {"prompt_version": "v1", "model": "Seedance 2.5", "mode": "mixed2video"}
    node = {"prompt_version": "v2", "model": "Seedance 2.5", "modeType": "mixed2video"}
    problems = skill_audit.check_node_binding(audit, node)
    assert any("PROMPT_VERSION_MISMATCH" in p for p in problems)


def test_model_and_mode_mismatch_also_block():
    audit = {"prompt_version": "v2", "model": "Seedance 2.5", "mode": "mixed2video"}
    assert skill_audit.check_node_binding(audit, {"prompt_version": "v2", "model": "Other",
                                                  "modeType": "mixed2video"})
    assert skill_audit.check_node_binding(audit, {"prompt_version": "v2", "model": "Seedance 2.5",
                                                  "modeType": "R2V"})


def test_created_on_the_platform_is_not_production_ready():
    """MCP saying 'operation completed' only means CREATED."""
    full = {section: "x" for section in skill_audit.REQUIRED_PROMPT_SECTIONS}
    node = {"platform_node_status": "CREATED", "prompt_version": "v2", "model": "Seedance 2.5",
            "modeType": "mixed2video", "audit": {"prompt_version": "v2", "model": "Seedance 2.5",
                                                 "mode": "mixed2video"}}
    result = skill_audit.node_readiness(audit_ok=True, asset_gate_ok=False, node=node, prompt=full)
    assert result["platform_node_status"] == "CREATED"
    assert result["production_readiness"] == "FAIL"
    assert "ASSET_GATE_NOT_READY" in result["codes"]
    assert "PLATFORM_NODE_CREATED_BUT_NOT_PRODUCTION_READY" in result["codes"]


def test_ready_only_when_everything_holds():
    full = {section: "x" for section in skill_audit.REQUIRED_PROMPT_SECTIONS}
    node = {"platform_node_status": "CREATED", "prompt_version": "v2", "model": "Seedance 2.5",
            "modeType": "mixed2video", "audit": {"prompt_version": "v2", "model": "Seedance 2.5",
                                                 "mode": "mixed2video"}}
    result = skill_audit.node_readiness(audit_ok=True, asset_gate_ok=True, node=node, prompt=full)
    assert result["ready"] and result["production_readiness"] == "PRODUCTION_READY"
    assert result["codes"] == []
