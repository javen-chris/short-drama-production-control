"""Reconciling claims against proof, and checking that QA is by another model.

Two questions the board could not previously answer:

1. Did the run follow the declared protocol, or only say that it did? A step
   recorded COMPLETED whose evidence file is absent is the shape of every
   incident so far - and it used to render as a pass.
2. Who did the QA? Protocol requires a different model than the producer, so a
   QA event signed by the same actor is self-review, not review.
"""
import json
from pathlib import Path

import pytest

from production_control import orchestrator, step_audit
from production_control.progress import append_event as _append_event

CHAIN = {"steps": [
    {"skill": "short-drama-production-router", "after": []},
    {"skill": "short-drama-prompt-compiler", "after": ["short-drama-production-router"]},
    {"skill": "short-drama-production-qa", "after": ["short-drama-prompt-compiler"],
     "mode": "pre_generation"},
]}


def append_event(*args, **kwargs):
    """Test helper: the routed GPT QA model writes all trace events."""
    role = kwargs.get("role", "producer")
    actor = kwargs.setdefault("actor", "gpt-5.6-luna")
    kwargs.setdefault("writer_model", actor if role == "qa" else "gpt-5.6-terra")
    if kwargs.get("evidence"):
        kwargs.setdefault("affected_files", [kwargs["evidence"]])
    if role == "qa":
        kwargs.setdefault("task_id", "RUN-EP-EXAMPLE-A1")
        kwargs.setdefault("version", "v1")
        kwargs.setdefault("qa_level", "C")
        kwargs.setdefault("qa_conclusion", "PASS")
        kwargs.setdefault("elapsed_seconds", 15)
        kwargs.setdefault("execution_model", "gpt-5.6-luna")
        kwargs.setdefault("blocking_issues", [])
        kwargs.setdefault("next_step", "继续当前流程")
    return _append_event(*args, **kwargs)


def _project(tmp_path: Path, chain: dict | None = None) -> Path:
    root = tmp_path / "proj"
    (root / "workflow").mkdir(parents=True)
    orchestrator.start(None, chain or CHAIN, "RUN-EP-EXAMPLE-A1", "C1", project_root=root,
                       segment="A1", segment_title="转运", series="示例系列", episode="EP-EXAMPLE")
    return root


def _state(root: Path) -> dict:
    return json.loads((root / "workflow" / "runs" / "RUN-EP-EXAMPLE-A1.json").read_text(encoding="utf-8"))


def _write(root: Path, rel: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")


def _submit(root: Path, step: str, **kw):
    return append_event(root, "RUN-EP-EXAMPLE-A1", step=step, actor="gpt-5.6-luna", role="producer", **kw)


def _pass(root: Path, step: str, **kw):
    return append_event(root, "RUN-EP-EXAMPLE-A1", step=step, actor="gpt-5.6-terra", role="qa",
                        outcome="COMPLETED", **kw)


def _rows(result: dict) -> dict:
    return {row["step"]: row for row in result["steps"]["rows"]}


def test_a_step_claimed_without_its_evidence_is_not_a_pass(tmp_path):
    """The whole point: a claim is not proof."""
    root = _project(tmp_path)
    _write(root, "workflow/router_note.md")
    append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-production-router",
                 skill_id="short-drama-production-router", evidence="workflow/router_note.md",
                 actor="gpt-5.6-luna")
    # Claim the prompt step, pointing at a file that is not there.
    state = _state(root)
    state["events"].append({"step": "short-drama-prompt-compiler", "outcome": "COMPLETED",
                            "evidence": "workflow/does_not_exist.md", "at": "2026-09-25T00:00:00+08:00"})
    (root / "workflow" / "runs" / "RUN-EP-EXAMPLE-A1.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8")

    result = step_audit.audit_steps(_state(root), root, CHAIN)
    rows = _rows({"steps": result})
    assert rows["short-drama-prompt-compiler"]["verdict"] == step_audit.CLAIMED_NO_EVIDENCE
    assert any("CLAIMED_NO_EVIDENCE" in e for e in step_audit.audit_run(_state(root), root, CHAIN)["errors"])


def test_legacy_list_evidence_is_audited_without_crashing(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/one.md")
    state = _state(root)
    state["events"].append({
        "step": "protocol_bootstrap", "outcome": "COMPLETED",
        "evidence": ["workflow/one.md", "workflow/missing.md"],
    })

    result = step_audit.audit_steps(state, root, CHAIN)
    row = next(item for item in result["rows"] if item["step"] == "protocol_bootstrap")
    assert row["verdict"] == step_audit.EXTRA
    assert row["evidence_ok"] is False


def test_legacy_list_evidence_with_existing_refs_does_not_crash(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/one.md")
    _write(root, "workflow/two.md")
    state = _state(root)
    state["events"].append({
        "step": "protocol_bootstrap", "outcome": "COMPLETED",
        "evidence": ["workflow/one.md", "workflow/two.md"],
    })

    result = step_audit.audit_steps(state, root, CHAIN)
    row = next(item for item in result["rows"] if item["step"] == "protocol_bootstrap")
    assert row["evidence_ok"] is True


def test_a_declared_step_nobody_did_is_reported_as_missing(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/router_note.md")
    _submit(root, "short-drama-production-router",
            skill_id="short-drama-production-router", evidence="workflow/router_note.md",
            protocol_refs=["00_自动化生产唯一入口_v3.0.md",
                           "核心自动化生产包/02_任务路由与Gate_v3.0.md",
                           "24_资产索引与RUN恢复规则_v1.md"])
    _pass(root, "short-drama-production-router",
          skill_id="short-drama-production-router", evidence="workflow/router_note.md",
          protocol_refs=["00_自动化生产唯一入口_v3.0.md",
                         "核心自动化生产包/02_任务路由与Gate_v3.0.md",
                         "24_资产索引与RUN恢复规则_v1.md"])

    result = step_audit.audit_steps(_state(root), root, CHAIN)
    rows = _rows({"steps": result})
    assert rows["short-drama-production-router"]["verdict"] == step_audit.OK
    assert rows["short-drama-prompt-compiler"]["verdict"] == step_audit.NOT_CLAIMED
    assert rows["short-drama-production-qa"]["verdict"] == step_audit.NOT_CLAIMED


def test_evidence_that_exists_but_skipped_its_protocol_read_is_flagged(tmp_path):
    """A real artefact plus no record of reading the governing document is not OK."""
    root = _project(tmp_path)
    _write(root, "workflow/prompt_v1.md")
    _submit(root, "short-drama-prompt-compiler",
            skill_id="short-drama-prompt-compiler", evidence="workflow/prompt_v1.md")

    result = step_audit.audit_steps(_state(root), root, CHAIN)
    row = _rows({"steps": result})["short-drama-prompt-compiler"]
    assert row["verdict"] == step_audit.CLAIMED_NO_READ
    assert "12_真人短剧Prompt与故事本弹性标准_v3.0.md" in row["missing_reads"]


def test_qa_by_the_same_model_as_the_producer_is_a_violation(tmp_path):
    """A model grading its own homework is the thing the rule exists to stop."""
    root = _project(tmp_path)
    _write(root, "workflow/prompt_v1.md")
    append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-prompt-compiler",
                 skill_id="short-drama-prompt-compiler", evidence="workflow/prompt_v1.md",
                 actor="gpt-5.6-luna")

    state = _state(root)
    state["events"].append({"step": "short-drama-production-qa", "outcome": "COMPLETED",
                            "actor": "gpt-5.6-luna", "at": "2026-09-25T00:10:00+08:00"})
    qa = step_audit.audit_qa_independence(state, CHAIN)
    assert qa["status"] == step_audit.SELF_QA_VIOLATION
    assert qa["independent"] is False


def test_qa_by_a_different_model_counts_as_independent(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/prompt_v1.md")
    append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-prompt-compiler",
                 skill_id="short-drama-prompt-compiler", evidence="workflow/prompt_v1.md",
                 actor="gpt-5.6-luna")

    state = _state(root)
    state["events"].append({"step": "short-drama-production-qa", "outcome": "COMPLETED",
                            "actor": "gpt-5.6-terra", "writer_model": "gpt-5.6-terra",
                            "gate": "G5", "at": "2026-09-25T00:10:00+08:00"})
    qa = step_audit.audit_qa_independence(state, CHAIN)
    assert qa["status"] == step_audit.INDEPENDENT
    assert qa["rounds"][0]["producer_actor"] == "gpt-5.6-luna"


def test_historical_glm_or_unrouted_qa_cannot_render_green(tmp_path):
    root = _project(tmp_path)
    state = _state(root)
    state["events"] = [
        {"step": "short-drama-prompt-compiler", "outcome": "SUBMITTED_FOR_QA",
         "role": "producer", "actor": "gpt-5.6-luna", "writer_model": "glm-5.3-flash"},
        {"step": "short-drama-prompt-compiler", "outcome": "COMPLETED",
         "role": "qa", "actor": "glm-5.3-flash", "writer_model": "glm-5.3-flash"},
    ]
    qa = step_audit.audit_qa_passes(state, root)
    row = next(r for r in qa["rows"] if r["step"] == "short-drama-prompt-compiler")
    assert row["state"] == "QA_INVALID"
    assert qa["passed"] == 0


def test_current_routed_qa_with_metadata_can_render_green(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/prompt_v1.md")
    _submit(root, "short-drama-prompt-compiler", evidence="workflow/prompt_v1.md",
            task_id="TASK-1", version="v1", qa_level="C")
    _pass(root, "short-drama-prompt-compiler", evidence="workflow/prompt_v1.md",
          task_id="TASK-1", version="v1", qa_level="C")
    qa = step_audit.audit_qa_passes(_state(root), root)
    row = next(r for r in qa["rows"] if r["step"] == "short-drama-prompt-compiler")
    assert row["state"] == "QA_PASSED"


def test_qa_without_recorded_actors_is_not_treated_as_a_pass(tmp_path):
    """Unverifiable independence is not independence."""
    root = _project(tmp_path)
    state = _state(root)
    state["events"] = [
        {"step": "short-drama-prompt-compiler", "outcome": "COMPLETED"},
        {"step": "short-drama-production-qa", "outcome": "COMPLETED"},
    ]
    qa = step_audit.audit_qa_independence(state, CHAIN)
    assert qa["status"] == step_audit.QA_ACTOR_UNKNOWN
    assert qa["independent"] is False


def test_append_event_refuses_to_write_a_self_review(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/prompt_v1.md")
    append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-prompt-compiler",
                 skill_id="short-drama-prompt-compiler", evidence="workflow/prompt_v1.md",
                 actor="gpt-5.6-luna")

    with pytest.raises(ValueError, match="SELF_QA_VIOLATION"):
        append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-prompt-compiler",
                     evidence="workflow/prompt_v1.md", actor="gpt-5.6-luna",
                     role="qa", outcome="COMPLETED")


def test_no_flag_can_allow_a_self_review(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/prompt_v1.md")
    append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-prompt-compiler",
                 skill_id="short-drama-prompt-compiler", evidence="workflow/prompt_v1.md",
                 actor="gpt-5.6-luna")

    with pytest.raises(ValueError, match="SELF_QA_VIOLATION"):
        append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-prompt-compiler",
                     evidence="workflow/prompt_v1.md", actor="gpt-5.6-luna",
                     role="qa", outcome="COMPLETED", allow_self_qa=True)


def test_append_event_records_the_actor(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/router_note.md")
    state = append_event(root, "RUN-EP-EXAMPLE-A1", step="short-drama-production-router",
                         skill_id="short-drama-production-router",
                         evidence="workflow/router_note.md", actor="gpt-5.6-luna")
    assert state["events"][-1]["actor"] == "gpt-5.6-luna"


def test_the_board_shows_the_one_table_that_matters(tmp_path):
    """One row per step: done, by whom, checked, by whom, backed by what."""
    from production_control.run_report import render_html, summarize

    root = _project(tmp_path)
    state = _state(root)
    state["events"] = [{"step": "short-drama-prompt-compiler", "outcome": "COMPLETED",
                        "evidence": "workflow/gone.md"}]
    summary = summarize(state, CHAIN, None, root)
    page = render_html(summary)
    assert "协议步骤" in page
    assert "无实证" in page          # claimed, nothing behind it
    assert "生产 → QA" in page       # who produced and who signed it off, one line
    assert 'data-gate="G5"' in page and "Prompt 编译与生成前 QA" in page  # and which Gate
    # This run has no off-chain events, so the page must not mention any: a
    # permanent "链外步骤 0" is a row of noise explaining nothing. The count
    # appears in the progress strip only when there is something to count.
    assert "链外步骤" not in page
    assert '<details class="offchain">' not in page


def test_a_run_that_invents_its_own_step_names_is_flagged(tmp_path):
    """EP-EXAMPLE/A1 recorded six steps, none of them a step the protocol declares.

    It read the protocol, then did something else and called it progress. Every
    declared step being absent while invented ones are present is not "behind
    schedule" - it is the protocol being replaced.
    """
    root = _project(tmp_path)
    _write(root, "workflow/router_note.md")
    state = _state(root)
    state["events"] = [
        {"step": "protocol-read", "outcome": "COMPLETED", "evidence": "workflow/router_note.md"},
        {"step": "G2-shot-confirm", "outcome": "COMPLETED", "evidence": "workflow/router_note.md"},
    ]
    (root / "workflow" / "runs" / "RUN-EP-EXAMPLE-A1.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8")

    result = step_audit.audit_run(_state(root), root, CHAIN)
    assert result["status"] == step_audit.NON_COMPLIANT
    assert result["out_of_chain_steps"] == ["protocol-read", "G2-shot-confirm"]
    assert any(e.startswith("OUT_OF_CHAIN_STEPS") for e in result["errors"])
    assert any(e.startswith("PROTOCOL_BYPASSED") for e in result["errors"])


def test_a_run_that_has_not_started_is_not_a_violation(tmp_path):
    """A segment with a file and no events is pending, not cheating."""
    root = _project(tmp_path)
    result = step_audit.audit_run(_state(root), root, CHAIN)
    assert result["status"] == step_audit.IN_PROGRESS
    assert result["errors"] == []
    assert len(result["missing_steps"]) == 3
    assert result["qa"]["status"] == step_audit.QA_NOT_RUN


def test_a_finished_run_missing_declared_steps_is_flagged(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/router_note.md")
    state = _state(root)
    state["status"] = "COMPLETED"
    state["events"] = [{"step": "short-drama-production-router", "outcome": "COMPLETED",
                        "evidence": "workflow/router_note.md",
                        "protocol_refs": [{"path": "00_自动化生产唯一入口_v3.0.md"},
                                          {"path": "核心自动化生产包/02_任务路由与Gate_v3.0.md"}]}]
    (root / "workflow" / "runs" / "RUN-EP-EXAMPLE-A1.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8")

    result = step_audit.audit_run(_state(root), root, CHAIN)
    assert any(e.startswith("PROTOCOL_STEPS_INCOMPLETE") for e in result["errors"])


# --- Off-chain activity must never be invisible ------------------------------
# The board used to drop any event whose step name the protocol does not declare
# unless it said COMPLETED. An agent that spends an afternoon writing
# SUBMITTED_FOR_QA / BLOCKED events under invented names therefore produced a
# board that never moved - the work was real, the names were wrong, and the user
# was told nothing. Every undeclared step is now surfaced whatever its outcome.

def test_an_off_chain_event_is_shown_even_when_it_is_not_completed(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/note.md")
    _submit(root, "g6-reference-integrity", outcome="BLOCKED", off_protocol=True,
            evidence="workflow/note.md", reason="节点读回不一致")

    rows = _rows(step_audit.audit_run(_state(root), root, CHAIN))
    assert "g6-reference-integrity" in rows
    assert rows["g6-reference-integrity"]["verdict"] == step_audit.EXTRA
    assert rows["g6-reference-integrity"]["outcome"] == "BLOCKED"


def test_every_off_chain_outcome_reaches_the_board(tmp_path):
    """SUBMITTED_FOR_QA and PAUSED_EXCEPTION used to be dropped entirely."""
    root = _project(tmp_path)
    for index, outcome in enumerate(("SUBMITTED_FOR_QA", "BLOCKED", "PAUSED_EXCEPTION")):
        _write(root, f"workflow/note{index}.md")
        _submit(root, f"g6-invented-{index}", outcome=outcome, off_protocol=True,
                evidence=f"workflow/note{index}.md")

    result = step_audit.audit_run(_state(root), root, CHAIN)
    rows = _rows(result)
    for index in range(3):
        assert f"g6-invented-{index}" in rows
    assert result["steps"]["counts"].get(step_audit.EXTRA) == 3


def test_an_off_chain_step_appears_once_showing_its_latest_event(tmp_path):
    root = _project(tmp_path)
    _write(root, "workflow/a.md")
    _write(root, "workflow/b.md")
    _submit(root, "g6-preflight-11refs", outcome="BLOCKED", off_protocol=True,
            evidence="workflow/a.md")
    _submit(root, "g6-preflight-11refs", outcome="SUBMITTED_FOR_QA", off_protocol=True,
            evidence="workflow/b.md")

    rows = _rows(step_audit.audit_run(_state(root), root, CHAIN))
    assert rows["g6-preflight-11refs"]["outcome"] == "SUBMITTED_FOR_QA"
    assert rows["g6-preflight-11refs"]["evidence"] == "workflow/b.md"
