import json
import subprocess
import sys
from pathlib import Path

from production_control import orchestrator, run_index, step_audit


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "workflow").mkdir(parents=True)
    chain = {"steps": [{"skill": "short-drama-production-router", "after": []}]}
    orchestrator.start(None, chain, "RUN-QA-1", "C1", project_root=root,
                       segment="A1", segment_title="Test", series="Series", episode="EP01")
    (root / "workflow" / "artifact.md").write_text("v1 artifact", encoding="utf-8")
    (root / "workflow" / "qa.md").write_text("Independent QA evidence", encoding="utf-8")
    return root


def _run(root: Path, *, conclusion: str = "PASS", elapsed: str = "40",
         level: str = "C") -> subprocess.CompletedProcess:
    tool = Path(__file__).resolve().parents[1] / "tools" / "qa_verdict.py"
    return subprocess.run(
        [sys.executable, str(tool), str(root), "--run", "RUN-QA-1",
         "--step", "S01", "--gate", "G0",
         "--execution-model", "gpt-5.6-luna", "--qa-actor", "gpt-5.6-terra",
         "--task-id", "TASK-1", "--version", "v1", "--qa-level", level,
         "--elapsed-seconds", elapsed, "--conclusion", conclusion,
         "--artifact-evidence", "workflow/artifact.md", "--evidence", "workflow/qa.md",
         "--next-step", "继续当前流程", "--affected-file", "workflow/artifact.md"],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_routed_qa_model_writes_submission_and_verdict(tmp_path):
    root = _project(tmp_path)
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(run_index.run_path(root, "RUN-QA-1").read_text(encoding="utf-8"))
    submit, verdict = state["events"]
    assert submit["actor"] == "gpt-5.6-luna"
    assert submit["writer_model"] == "gpt-5.6-terra"
    assert verdict["actor"] == verdict["writer_model"] == "gpt-5.6-terra"
    assert verdict["execution_model"] == "gpt-5.6-luna"
    assert verdict["qa_conclusion"] == "PASS"
    assert step_audit.audit_qa_passes(state, root)["passed"] == 1


def test_a_level_over_180_seconds_is_recorded_as_timeout_not_pass(tmp_path):
    root = _project(tmp_path)
    result = _run(root, elapsed="181", level="A")
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(run_index.run_path(root, "RUN-QA-1").read_text(encoding="utf-8"))
    assert state["events"][-1]["qa_conclusion"] == "TIMEOUT"
    assert state["events"][-1]["outcome"] == "WAITING_APPROVAL"
    assert step_audit.audit_qa_passes(state, root)["passed"] == 0
