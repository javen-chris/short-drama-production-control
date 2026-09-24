"""The board has to answer three questions without opening a log.

1. Is the agent still reporting, or has it gone quiet?
2. What does the producing window say for itself (workflow/project_state.json)?
3. Can I click a segment that has not started yet without being told "not found"?
"""
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from production_control import run_index, run_server
from production_control.run_report import render_project_html, reporting_state

PIPELINE = ["short-drama-production-router", "short-drama-production-qa"]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "workflow" / "runs").mkdir(parents=True)
    return root


def _write_run(root: Path, run_id: str, *, minutes_ago: int | None = None) -> None:
    at = ""
    if minutes_ago is not None:
        at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    state = {
        "run_id": run_id,
        "segment": run_id.rsplit("-", 1)[-1],
        "segment_title": f"{run_id} 段",
        "status": "RUNNING",
        "current_step": PIPELINE[0],
        "pipeline": PIPELINE,
        "completed_steps": [PIPELINE[0]] if at else [],
        "events": [{"step": PIPELINE[0], "outcome": "COMPLETED", "at": at}] if at else [],
    }
    (root / "workflow" / "runs" / f"{run_id}.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8")


def test_a_project_with_only_a_segment_list_is_recognised(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "segments.json").write_text(
        json.dumps({"project": "EP03", "episode": "EP03", "segments": [{"segment": "A1", "title": "开场"}]},
                   ensure_ascii=False), encoding="utf-8")

    assert run_index.has_trace(root)
    index = run_index.project_index(root)
    assert [row["run_id"] for row in index["runs"]] == ["RUN-EP03-A1"]


def test_every_source_counts_the_same_segments(tmp_path):
    """Menu, static export and live page used to disagree. They must not."""
    root = _project(tmp_path)
    (root / "workflow" / "segments.json").write_text(
        json.dumps({"project": "EP03", "episode": "EP03", "segments": [
            {"segment": f"A{n}", "title": f"第{n}段"} for n in (1, 2, 3)]}, ensure_ascii=False),
        encoding="utf-8")
    _write_run(root, "RUN-EP03-A1", minutes_ago=1)

    index = run_index.project_index(root)
    assert len(index["runs"]) == 3
    view = run_server.current_view(root)
    assert len(view["runs"]) == 3
    assert view["counts"]["not_started"] == 2


def test_quiet_agent_is_flagged_on_the_page(tmp_path):
    root = _project(tmp_path)
    _write_run(root, "RUN-EP03-A1", minutes_ago=90)

    view = run_server.current_view(root)
    assert view["reporting"]["level"] == "stale"
    page = render_project_html(view, live=True)
    assert "最后回传" in page
    assert "分钟没有回传" in page


def test_a_fresh_report_is_not_flagged(tmp_path):
    root = _project(tmp_path)
    _write_run(root, "RUN-EP03-A1", minutes_ago=1)

    view = run_server.current_view(root)
    assert view["reporting"]["level"] == "ok"


def test_project_state_file_surfaces_as_a_heartbeat(tmp_path):
    """A window that only writes its own status file must not look dead."""
    root = _project(tmp_path)
    today = datetime.now(timezone.utc).date().isoformat()
    (root / "workflow" / "project_state.json").write_text(
        json.dumps({"stage": "A1生产前准备完成", "status": "WAITING_USER_GENERATION",
                    "updated": today, "blockers": ["libtv Token 无效"]}, ensure_ascii=False),
        encoding="utf-8")

    view = run_server.current_view(root)
    assert view["project_state"]["stage"] == "A1生产前准备完成"
    page = render_project_html(view, live=True)
    # The stage and the blockers used to be a standalone panel; they are now a
    # line in the global alert list, which is the only place they still matter.
    assert "libtv Token 无效" in page
    assert view["reporting"]["level"] != "none"


def test_unstarted_segment_opens_instead_of_404(tmp_path):
    root = _project(tmp_path)
    (root / "workflow" / "segments.json").write_text(
        json.dumps({"project": "EP03", "episode": "EP03", "segments": [
            {"segment": "A1", "title": "开场"}, {"segment": "A2", "title": "突入"}]}, ensure_ascii=False),
        encoding="utf-8")
    _write_run(root, "RUN-EP03-A1")

    httpd = run_server.serve(root, port=0, open_browser=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        page = urllib.request.urlopen(f"{base}/run/RUN-EP03-A2", timeout=10).read().decode("utf-8")
        assert "还没有开始生产" in page
        try:
            urllib.request.urlopen(f"{base}/run/RUN-EP03-A9", timeout=10)
            raise AssertionError("expected 404 for a segment that does not exist")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_reporting_state_levels():
    assert reporting_state(2)["level"] == "ok"
    assert reporting_state(60)["level"] == "stale"
    assert reporting_state(None, started=1)["level"] == "none"
    assert reporting_state(None, started=0)["level"] == "idle"


def test_run_details_load_even_when_the_index_says_runs(tmp_path):
    """Rows used to store "runs/<id>.json" while files live in workflow/runs/.

    That spelling named a file that exists as one that does not, so every
    per-step detail silently failed to load and a moving project looked
    untouched. A stored path is a hint, not an authority.
    """
    from production_control.run_report import summarize_project

    root = _project(tmp_path)
    _write_run(root, "RUN-EP03-A1", minutes_ago=1)

    assert run_index.resolve_run_path(root, "RUN-EP03-A1", "runs/RUN-EP03-A1.json").is_file()

    # A row still carrying the old spelling must still get its details.
    index = run_index.project_index(root)
    for row in index["runs"]:
        row["path"] = f"runs/{row['run_id']}.json"
    view = summarize_project(index, root, with_details=True)
    row = next(r for r in view["runs"] if r["run_id"] == "RUN-EP03-A1")
    assert row["detail"] is not None
    assert row["detail"]["progress"]["completed"] >= 1


def test_progress_counts_steps_written_outside_the_pipeline(tmp_path):
    """Seven finished steps reported as 0/12 is worse than showing nothing."""
    root = _project(tmp_path)
    (root / "workflow" / "runs" / "RUN-EP03-A1.json").write_text(json.dumps({
        "run_id": "RUN-EP03-A1", "segment": "A1", "status": "BLOCKED",
        "pipeline": ["short-drama-production-router", "short-drama-production-qa"],
        "completed_steps": ["protocol-read", "G2-shot-confirm", "G5-prompt"],
        "events": [{"step": "G5-prompt", "outcome": "COMPLETED", "at": "2026-09-24T10:00:00+00:00"}],
    }, ensure_ascii=False), encoding="utf-8")

    view = run_server.current_view(root)
    row = next(r for r in view["runs"] if r["run_id"] == "RUN-EP03-A1")
    assert row["progress"]["completed"] == 3
    assert row["progress"]["total"] == 5  # 2 pipeline steps + 3 recorded off-pipeline
    assert row["detail"]["custom_steps"] == ["protocol-read", "G2-shot-confirm", "G5-prompt"]


def test_an_empty_gate_or_audit_state_is_still_visible(tmp_path):
    """An empty list reads as "nothing wrong" to a human skimming the page.

    It means the opposite: nothing was ever checked. That used to be two
    standalone panels and is now two lines in the alert list - but the rule
    stands: absence must be stated, never left blank.
    """
    root = _project(tmp_path)
    _write_run(root, "RUN-EP03-A1", minutes_ago=1)

    view = run_server.current_view(root)
    assert view["gate_tokens"] == [] and view["skill_audits"] == []
    page = render_project_html(view, live=True)
    assert "一条都没有" in page
    assert "没有任何一段通过过建节点前置门禁" in page
    assert "没有任何 Prompt 跑过 G5.1 审计" in page


def test_the_index_is_never_asked_to_carry_a_path_the_file_lacks(tmp_path):
    """A row written now must resolve without the compatibility fallback."""
    root = _project(tmp_path)
    _write_run(root, "RUN-EP03-A1", minutes_ago=1)
    index = run_index.sync_index(root, run_index.load_index(root))
    row = next(r for r in index["runs"] if r["run_id"] == "RUN-EP03-A1")
    assert row["path"].startswith("workflow/")
    assert (root / row["path"]).is_file()
    # Round-tripping through the file keeps the resolvable spelling.
    run_index.save_index(root, index)
    reloaded = next(r for r in run_index.load_index(root)["runs"] if r["run_id"] == "RUN-EP03-A1")
    assert (root / reloaded["path"]).is_file()
