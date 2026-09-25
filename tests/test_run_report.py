import json

from production_control.run_report import render_html, render_text, summarize

STATE = {
    "run_id": "RUN-T1",
    "contract_id": "C1",
    "current_step": "short-drama-image-generator",
    "status": "PAUSED_EXCEPTION",
    "pipeline": ["short-drama-script-breakdown", "short-drama-image-generator", "short-drama-production-qa"],
    "completed_steps": ["short-drama-script-breakdown", "short-drama-image-generator"],
    "pending_decision": "第 2 格手部异常，判定 FAIL",
    "events": [
        {
            "step": "short-drama-script-breakdown", "outcome": "COMPLETED", "at": "2026-09-20T13:00:00Z",
            "skill_id": "short-drama-script-breakdown", "evidence": "qa/breakdown.json",
            "validator": "contract_validator", "attestation_id": "ATT-1",
            "protocol_refs": [{"path": "09_脚本优化与分镜拆解规范_v3.0.md"}],
        },
        {
            "step": "short-drama-image-generator", "outcome": "COMPLETED", "at": "2026-09-20T13:05:00Z",
            "skill_id": "short-drama-image-generator", "evidence": "qa/image.json",
            "protocol_refs": [{"path": "16_生图渠道规则_v3.0.md"}, {"path": "14_RH生图渠道与GPT通道现状_v3.0.md"}],
        },
        {
            "step": "short-drama-production-qa", "outcome": "PAUSED_EXCEPTION", "at": "2026-09-20T13:09:00Z",
            "reason": "第 2 格手部异常，判定 FAIL", "evidence": "qa/post_u01.json",
        },
    ],
}


def test_summary_counts_progress_and_states():
    summary = summarize(STATE)
    assert summary["progress"] == {"completed": 2, "total": 3}
    states = {item["step"]: item["state_label"] for item in summary["steps"]}
    assert states["short-drama-image-generator"] == "已完成（QA 通过）"
    assert states["short-drama-production-qa"] == "已挂起（异常）"


def test_completed_step_without_required_read_is_a_gap():
    state = json.loads(json.dumps(STATE))
    for event in state["events"]:
        if event["step"] == "short-drama-image-generator":
            event["protocol_refs"] = [{"path": "16_生图渠道规则_v3.0.md"}]
    summary = summarize(state)
    assert summary["compliance"]["status"] == "NON_COMPLIANT"
    assert any("14_RH生图渠道与GPT通道现状_v3.0.md" in e for e in summary["compliance"]["errors"])


def test_pending_step_is_not_reported_as_a_violation():
    summary = summarize(STATE)
    qa = next(item for item in summary["steps"] if item["step"] == "short-drama-production-qa")
    assert qa["missing_required"] == []
    assert all(read["status"] == "pending" for read in qa["reads"])


def test_paused_step_keeps_its_reason_visible():
    summary = summarize(STATE)
    qa = next(item for item in summary["steps"] if item["step"] == "short-drama-production-qa")
    assert "手部异常" in qa["reason"]
    assert qa["evidence"] == "qa/post_u01.json"


def test_text_report_mentions_each_step_and_the_compliance_verdict():
    text = render_text(summarize(STATE))
    assert "short-drama-image-generator" in text
    assert "合规检查" in text
    assert "已挂起（异常）" in text


def test_html_report_is_self_contained_and_escapes_content():
    state = json.loads(json.dumps(STATE))
    state["run_id"] = "<script>alert(1)</script>"
    html = render_html(summarize(state))
    assert html.startswith("<!doctype html>")
    assert "http://" not in html.split("</style>")[0].replace("http://www.w3.org", "")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_step_table_carries_the_verdict_per_step():
    """The page's whole job: one line per declared step, verdict included.

    The old per-step "协议读取与执行过程" listing was a second, overlapping view
    of the same thing and is gone. What replaced it must still say, per step,
    who produced it, who checked it, and whether anything backs it up.
    """
    html = render_html(summarize(STATE))
    assert "生产 → QA" in html
    assert "协议步骤" in html
    assert "class=\"vp " in html


def test_the_table_is_led_by_the_gate_not_the_skill_slug():
    """A person reads Gates, not Skill ids.

    The board used to print `short-drama-production-router` with an empty Gate
    column, because no mapping from Skill to Gate existed. The Gate is the
    protocol's own vocabulary, so it has to lead - and every declared Skill has
    to have one, or the column goes back to being empty.
    """
    from production_control import gate_map
    from production_control.step_audit import load_chain

    html = render_html(summarize(STATE))
    # The Gate letters and the Chinese Gate name are separate elements, so the
    # assertion is on both rather than on one concatenated string.
    assert 'class="gate">G1<' in html
    assert "秒表脚本" in html
    assert "脚本拆解为镜头与生产单元" in html  # and not the raw slug as the label

    # Every Skill the protocol declares must map to a Gate, and every Gate it
    # names must be a real Gate. The mapping is only useful if it is total.
    for row in load_chain().get("steps", []):
        skill = row["skill"]
        gates = gate_map.gates_of(skill)
        assert gates, f"{skill} has no Gate"
        for gate in gates:
            assert gate in gate_map.GATE_NAMES, f"{skill} maps to unknown {gate}"


def test_every_declared_skill_has_a_chinese_name():
    """The board must never show a bare slug as the primary label."""
    from production_control import gate_map
    from production_control.step_audit import load_chain

    for row in load_chain().get("steps", []):
        skill = row["skill"]
        label = gate_map.skill_label(skill)
        assert label and label != skill, f"{skill} has no Chinese name"


def test_an_unknown_step_still_renders_as_itself():
    """A project may record a step the console has never heard of.

    Substituting a placeholder would hide the one thing worth seeing: that the
    step is not in the declared chain.
    """
    from production_control import gate_map

    assert gate_map.skill_label("libtv-local-adapter") == "LibTV 提交适配"
    assert gate_map.skill_label("someone-elses-custom-step") == "someone-elses-custom-step"
    assert gate_map.gates_of("someone-elses-custom-step") == ()
    assert gate_map.gate_badge("someone-elses-custom-step") == ""
