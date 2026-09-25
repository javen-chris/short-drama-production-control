import json
import subprocess
import sys
from pathlib import Path

import pytest

from production_control import orchestrator, run_index
from production_control.progress import MissingEvidenceError, UnknownStepError, append_event

CHAIN = {"steps": [
    {"skill": "short-drama-production-router", "after": []},
    {"skill": "short-drama-image-generator", "after": ["short-drama-production-router"]},
    {"skill": "short-drama-production-qa", "after": ["short-drama-image-generator"]},
]}


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "workflow").mkdir(parents=True)
    orchestrator.start(None, CHAIN, "RUN-EP02-N3-A2", "C1", project_root=root,
                       segment="N3-A2", segment_title="苍烛陨落",
                       series="龙骨列车", episode="EP02")
    return root


def _fake_evidence(root: Path, step: str) -> str:
    """Write a real artefact so a helper call can satisfy the evidence rule.

    Since 2026-09-25 `append_event` refuses a step with no evidence path at all
    (MissingEvidenceError), not just one pointing at a missing file: a trace with
    `"evidence": ""` used to be accepted and looked recorded while showing
    nothing. The helpers below are about state transitions, not about evidence,
    so they supply a real file rather than each test restating the rule.
    """
    relative = f"workflow/evidence_{step.replace('/', '_')}.md"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"# {step} 证据\n", encoding="utf-8")
    return relative


def _submit(root: Path, run_id: str, step: str, **kw):
    """The producing model hands a step over. It cannot do more than this."""
    kw.setdefault("evidence", _fake_evidence(root, step))
    return append_event(root, run_id, step=step, actor="model-A", role="producer", **kw)


def _pass(root: Path, run_id: str, step: str, **kw):
    """A different model signs the step off. This is what makes it count."""
    kw.setdefault("evidence", _fake_evidence(root, step))
    return append_event(root, run_id, step=step, actor="model-B", role="qa",
                        outcome="COMPLETED", **kw)


def _complete(root: Path, run_id: str, step: str, **kw):
    _submit(root, run_id, step, **kw)
    return _pass(root, run_id, step, **kw)


def test_a_producer_may_submit_but_never_declare_a_step_done(tmp_path):
    """The rule the whole two-model design rests on."""
    root = _project(tmp_path)
    (root / "workflow" / "G0_上下文锁定.md").write_text("# G0 证据", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                         protocol_refs=["00_自动化生产唯一入口_v3.0.md"],
                         evidence="workflow/G0_上下文锁定.md", actor="model-A")
    assert state["completed_steps"] == []
    assert state["status"] == "SUBMITTED_FOR_QA"
    event = state["events"][-1]
    assert event["skill_id"] == "short-drama-production-router"
    assert event["protocol_refs"] == [{"path": "00_自动化生产唯一入口_v3.0.md"}]
    assert event["at"]
    assert event["outcome"] == "SUBMITTED_FOR_QA"
    assert event["role"] == "producer"

    with pytest.raises(PermissionError, match="WRITE_AUTHORITY_VIOLATION"):
        append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                     outcome="COMPLETED", actor="model-A",
                     evidence="workflow/G0_上下文锁定.md")


def test_the_qa_model_is_what_advances_the_segment(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "G0_上下文锁定.md").write_text("# G0 证据", encoding="utf-8")
    _submit(root, "RUN-EP02-N3-A2", "short-drama-production-router",
            evidence="workflow/G0_上下文锁定.md")
    state = _pass(root, "RUN-EP02-N3-A2", "short-drama-production-router",
                  evidence="workflow/G0_上下文锁定.md")
    assert state["completed_steps"] == ["short-drama-production-router"]
    assert state["current_step"] == "short-drama-image-generator"
    assert state["status"] == "RUNNING"


def test_one_call_records_a_step_and_advances_the_trace(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "G0.md").write_text("# 证据", encoding="utf-8")
    state = _complete(root, "RUN-EP02-N3-A2", "short-drama-production-router",
                      evidence="workflow/G0.md")
    event = state["events"][-1]
    assert event["skill_id"] == "short-drama-production-router"
    assert event["at"]
    assert event["outcome"] == "COMPLETED"
    assert event["role"] == "qa"
    # Both halves of the handover are on the trace: submit, then verdict.
    assert [e["outcome"] for e in state["events"]] == ["SUBMITTED_FOR_QA", "COMPLETED"]


def test_index_is_updated_so_the_page_sees_it(tmp_path):
    root = _project(tmp_path)
    _complete(root, "RUN-EP02-N3-A2", "short-drama-production-router")
    index = json.loads((root / "workflow" / "run_index.json").read_text(encoding="utf-8"))
    row = next(r for r in index["runs"] if r["run_id"] == "RUN-EP02-N3-A2")
    assert row["progress"]["completed"] == 1
    assert row["segment_title"] == "苍烛陨落"


def test_finishing_every_step_completes_the_run(tmp_path):
    root = _project(tmp_path)
    for step in ("short-drama-production-router", "short-drama-image-generator", "short-drama-production-qa"):
        state = _complete(root, "RUN-EP02-N3-A2", step)
    assert state["status"] == "COMPLETED"
    assert state["current_step"] == ""


def test_a_decision_point_is_recorded_as_waiting(tmp_path):
    root = _project(tmp_path)
    _complete(root, "RUN-EP02-N3-A2", "short-drama-production-router")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-image-generator",
                         actor="model-A",
                         evidence=_fake_evidence(root, "short-drama-image-generator"),
                         outcome="WAITING_APPROVAL", reason="G5 Prompt QA 完成，等待用户审阅")
    assert state["status"] == "WAITING_APPROVAL"
    assert "等待用户审阅" in state["pending_decision"]


def test_unknown_run_is_refused_with_a_clear_message(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(FileNotFoundError) as exc:
        append_event(root, "RUN-DOES-NOT-EXIST", step="x")
    assert "没有找到轨迹文件" in str(exc.value)


def test_evidence_that_does_not_exist_is_refused(tmp_path):
    """The rule the agent caught: never point at a file that is not there."""
    root = _project(tmp_path)
    with pytest.raises(FileNotFoundError) as exc:
        append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                     evidence="workflow/G0_上下文锁定_N3-A2.md")
    assert "证据文件不存在" in str(exc.value)
    # nothing was written
    state = json.loads(run_index.run_path(root, "RUN-EP02-N3-A2").read_text(encoding="utf-8"))
    assert state.get("events", []) == []


def test_evidence_that_exists_is_accepted(tmp_path):
    root = _project(tmp_path)
    proof = root / "workflow" / "G0_上下文锁定_N3-A2.md"
    proof.write_text("# G0 证据\n实际读取：00_自动化生产唯一入口_v3.0.md", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                         evidence="workflow/G0_上下文锁定_N3-A2.md")
    assert state["events"][-1]["evidence"] == "workflow/G0_上下文锁定_N3-A2.md"


def test_a_step_without_evidence_is_refused(tmp_path):
    """No path at all is a refusal, not a warning.

    It used to warn and write anyway, which made the 18-rule unenforceable: an
    agent could satisfy the checker by omitting the field, and the resulting
    event (`"evidence": ""`) is indistinguishable from one somebody typed by
    hand. That is the hole this closes.
    """
    root = _project(tmp_path)
    with pytest.raises(MissingEvidenceError):
        append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router")


def test_an_empty_evidence_string_is_also_refused(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(MissingEvidenceError):
        append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                     evidence="   ")


def test_an_evidence_waiver_is_marked_in_the_trace(tmp_path):
    """A waiver must stay visible, so a reader can tell it apart from an omission."""
    root = _project(tmp_path)
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                         allow_missing_evidence=True)
    assert state["events"][-1]["evidence_waived"] is True


def test_missing_evidence_can_be_explicitly_allowed(tmp_path):
    root = _project(tmp_path)
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                         evidence="不存在的.md", allow_missing_evidence=True)
    assert state["events"][-1]["evidence"] == "不存在的.md"


def test_the_cli_records_a_step(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "G0.md").write_text("# G0 证据", encoding="utf-8")
    tools = Path(__file__).resolve().parents[1] / "tools" / "append_event.py"
    result = subprocess.run(
        [sys.executable, str(tools), str(root), "--run", "RUN-EP02-N3-A2",
         "--step", "short-drama-production-router",
         "--protocol", "00_自动化生产唯一入口_v3.0.md",
         "--evidence", "workflow/G0.md"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert "已记录" in result.stdout
    assert "0/3 步" in result.stdout  # a submission is not progress yet
    assert "qa_verdict.py" in result.stdout  # and it says who must sign it off
    state = json.loads(run_index.run_path(root, "RUN-EP02-N3-A2").read_text(encoding="utf-8"))
    assert state["completed_steps"] == []
    assert state["events"][-1]["outcome"] == "SUBMITTED_FOR_QA"


def test_a_submitted_step_moves_the_segment_instead_of_being_ignored(tmp_path):
    """SUBMITTED_IN_PROGRESS used to be silently dropped: event written, status stuck."""
    root = _project(tmp_path)
    (root / "workflow" / "report.md").write_text("# 提交确认报告", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-prompt-compiler",
                         evidence="workflow/report.md", outcome="SUBMITTED_IN_PROGRESS")
    assert state["status"] == "SUBMITTED_IN_PROGRESS"
    assert state["events"][-1]["outcome"] == "SUBMITTED_IN_PROGRESS"


def test_finishing_with_a_caveat_completes_but_keeps_the_caveat(tmp_path):
    root = _project(tmp_path)
    for step in ("short-drama-production-router", "short-drama-image-generator"):
        (root / "workflow" / f"{step}.md").write_text("# 证据", encoding="utf-8")
        _complete(root, "RUN-EP02-N3-A2", step, evidence=f"workflow/{step}.md")
    (root / "workflow" / "qa.md").write_text("# QA", encoding="utf-8")
    _submit(root, "RUN-EP02-N3-A2", "short-drama-production-qa", evidence="workflow/qa.md")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-qa",
                         evidence="workflow/qa.md", actor="model-B", role="qa",
                         outcome="COMPLETED_WITH_CONTINUITY_CAVEAT")
    assert state["completed_steps"] == ["short-drama-production-router",
                                        "short-drama-image-generator",
                                        "short-drama-production-qa"]
    # Completed, but the caveat must survive rather than collapsing to COMPLETED.
    assert state["status"] == "COMPLETED_WITH_CONTINUITY_CAVEAT"


def test_an_outcome_nobody_recognises_is_refused(tmp_path):
    root = _project(tmp_path)
    with pytest.raises(ValueError) as exc:
        append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                     outcome="MADE_THIS_UP",
                     evidence=_fake_evidence(root, "short-drama-production-router"))
    assert "未知的 outcome" in str(exc.value)


def test_the_cli_accepts_a_submitted_outcome(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "rep.md").write_text("# 报告", encoding="utf-8")
    tools = Path(__file__).resolve().parents[1] / "tools" / "append_event.py"
    result = subprocess.run(
        [sys.executable, str(tools), str(root), "--run", "RUN-EP02-N3-A2",
         "--step", "short-drama-prompt-compiler", "--evidence", "workflow/rep.md",
         "--outcome", "SUBMITTED_IN_PROGRESS"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(run_index.run_path(root, "RUN-EP02-N3-A2").read_text(encoding="utf-8"))
    assert state["events"][-1]["outcome"] == "SUBMITTED_IN_PROGRESS"


# --- The write boundary keeps unplaceable names out of the trace ---------------
# A name nothing else recognises is a silent loss: the event is stored, the board
# cannot place it, and the work looks like it never happened. So the boundary
# canonicalises what it can, refuses what it cannot, and says which is which.

def test_an_invented_step_name_is_refused_at_the_write_boundary(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "ev.md").write_text("x", encoding="utf-8")
    with pytest.raises(UnknownStepError) as excinfo:
        append_event(root, "RUN-EP02-N3-A2", step="g6-reference-integrity",
                     evidence="workflow/ev.md")
    assert "g6-reference-integrity" in str(excinfo.value)


def test_the_refusal_lists_the_names_that_would_work(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "ev.md").write_text("x", encoding="utf-8")
    with pytest.raises(UnknownStepError) as excinfo:
        append_event(root, "RUN-EP02-N3-A2", step="g6-nonsense", evidence="workflow/ev.md")
    message = str(excinfo.value)
    assert "S08" in message
    assert "short-drama-prompt-compiler" in message


def test_off_protocol_records_an_auxiliary_step_on_purpose(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "ev.md").write_text("x", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="skill-audit-20260925",
                         evidence="workflow/ev.md", off_protocol=True)
    event = state["events"][-1]
    assert event["step"] == "skill-audit-20260925"
    assert event["off_protocol"] is True


def test_a_typed_skill_name_is_stored_canonically(tmp_path):
    """However it was spelled, the trace holds the declared skill."""
    root = _project(tmp_path)
    (root / "workflow" / "ev.md").write_text("x", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="Short_Drama_Prompt-Compiler",
                         evidence="workflow/ev.md")
    event = state["events"][-1]
    assert event["step"] == "short-drama-prompt-compiler"
    assert event["skill_id"] == "short-drama-prompt-compiler"
    assert event["step_id"] == "S08"


def test_a_stable_id_is_accepted_as_the_step(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "ev.md").write_text("x", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="s8", evidence="workflow/ev.md")
    assert state["events"][-1]["step"] == "short-drama-prompt-compiler"
    assert state["current_step"] == "short-drama-prompt-compiler"


def test_a_one_letter_slip_is_accepted_but_marked_as_a_guess(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "ev.md").write_text("x", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-prompt-compilor",
                         evidence="workflow/ev.md")
    event = state["events"][-1]
    assert event["step"] == "short-drama-prompt-compiler"
    assert event["step_matched_fuzzy"] > 0.9
    assert event["step_as_written"] == "short-drama-prompt-compilor"
