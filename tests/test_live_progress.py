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
    assert "实时回传" in page
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
    assert "A1生产前准备完成" in page
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
