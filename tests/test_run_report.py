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
    assert states["short-drama-image-generator"] == "已完成"
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


def test_html_marks_read_and_missing_rows():
    html = render_html(summarize(STATE))
    assert "已读" in html
    assert "class=\"step done\"" in html
