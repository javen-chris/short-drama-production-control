import json
import subprocess
import sys
from pathlib import Path

import pytest

from production_control import orchestrator, run_index
from production_control.progress import append_event

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


def test_one_call_records_a_step_and_advances_the_trace(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "G0_上下文锁定.md").write_text("# G0 证据", encoding="utf-8")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router",
                         protocol_refs=["00_自动化生产唯一入口_v3.0.md"],
                         evidence="workflow/G0_上下文锁定.md")
    assert state["completed_steps"] == ["short-drama-production-router"]
    assert state["current_step"] == "short-drama-image-generator"
    assert state["status"] == "RUNNING"
    event = state["events"][-1]
    assert event["skill_id"] == "short-drama-production-router"
    assert event["protocol_refs"] == [{"path": "00_自动化生产唯一入口_v3.0.md"}]
    assert event["at"]  # timestamped automatically
    assert event["outcome"] == "COMPLETED"


def test_index_is_updated_so_the_page_sees_it(tmp_path):
    root = _project(tmp_path)
    append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router")
    index = json.loads((root / "workflow" / "run_index.json").read_text(encoding="utf-8"))
    row = next(r for r in index["runs"] if r["run_id"] == "RUN-EP02-N3-A2")
    assert row["progress"]["completed"] == 1
    assert row["segment_title"] == "苍烛陨落"


def test_finishing_every_step_completes_the_run(tmp_path):
    root = _project(tmp_path)
    for step in ("short-drama-production-router", "short-drama-image-generator", "short-drama-production-qa"):
        state = append_event(root, "RUN-EP02-N3-A2", step=step)
    assert state["status"] == "COMPLETED"
    assert state["current_step"] == ""


def test_a_decision_point_is_recorded_as_waiting(tmp_path):
    root = _project(tmp_path)
    append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router")
    state = append_event(root, "RUN-EP02-N3-A2", step="short-drama-image-generator",
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


def test_a_step_without_evidence_warns_but_is_allowed(tmp_path):
    root = _project(tmp_path)
    with pytest.warns(UserWarning):
        append_event(root, "RUN-EP02-N3-A2", step="short-drama-production-router")


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
    assert "1/3 步" in result.stdout
    state = json.loads(run_index.run_path(root, "RUN-EP02-N3-A2").read_text(encoding="utf-8"))
    assert state["completed_steps"] == ["short-drama-production-router"]
