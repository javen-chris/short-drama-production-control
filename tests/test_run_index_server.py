import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from production_control import orchestrator, run_index, run_server

CHAIN = {
    "steps": [
        {"skill": "short-drama-production-router", "after": []},
        {"skill": "short-drama-image-generator", "after": ["short-drama-production-router"]},
        {"skill": "short-drama-production-qa", "after": ["short-drama-image-generator"]},
    ]
}
REFS = {
    "short-drama-production-router": ["00_自动化生产唯一入口_v3.0.md", "核心自动化生产包/02_任务路由与Gate_v3.0.md"],
    "short-drama-image-generator": ["16_生图渠道规则_v3.0.md", "14_RH生图渠道与GPT通道现状_v3.0.md"],
    "short-drama-production-qa": ["04_QA与文件治理_v3.0.md"],
}


def _handler(step):
    return lambda: {
        "skill_id": step,
        "protocol_refs": [{"path": p} for p in REFS[step]],
        "evidence": f"workflow/qa_reports/{step}.json",
    }


def _approvals():
    return set(orchestrator.plan_steps(CHAIN))


def _handlers():
    return {step: _handler(step) for step in REFS}


def _make_project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "workflow").mkdir(parents=True)
    return root


def test_one_file_per_segment_plus_one_index(tmp_path):
    root = _make_project(tmp_path)
    state = orchestrator.start(None, CHAIN, "RUN-EP02-U01", "C1", project_root=root,
                               segment="U01", segment_title="B-2A（物理格斗）",
                               series="龙骨列车", episode="EP02")
    for _ in range(len(CHAIN["steps"])):
        state = orchestrator.advance(state, _handlers(), _approvals())

    assert (root / "workflow" / "runs" / "RUN-EP02-U01.json").is_file()
    index = json.loads((root / "workflow" / "run_index.json").read_text(encoding="utf-8"))
    assert len(index["runs"]) == 1
    row = index["runs"][0]
    assert row["segment_title"] == "B-2A（物理格斗）"
    assert row["status"] == "COMPLETED"
    assert index["episode"] == "EP02" and index["series"] == "龙骨列车"


def test_precreated_segments_do_not_steal_the_active_marker(tmp_path):
    root = _make_project(tmp_path)
    active = orchestrator.start(None, CHAIN, "RUN-EP02-U01", "C1", project_root=root, segment="U01")
    orchestrator.advance(active, _handlers(), _approvals())  # U01 gains progress
    for n in (2, 3):
        orchestrator.start(None, CHAIN, f"RUN-EP02-U0{n}", "C1", project_root=root, segment=f"U0{n}")
    index = json.loads((root / "workflow" / "run_index.json").read_text(encoding="utf-8"))
    assert index["active_run_id"] == "RUN-EP02-U01"
    assert len(index["runs"]) == 3


def test_index_sync_picks_up_files_written_by_another_window(tmp_path):
    root = _make_project(tmp_path)
    (root / "workflow" / "runs").mkdir(parents=True)
    other = {
        "run_id": "RUN-EP02-U09", "segment": "U09", "segment_title": "B-9X",
        "status": "PAUSED_EXCEPTION", "pipeline": ["a", "b"], "completed_steps": ["a"],
        "events": [{"step": "a", "outcome": "COMPLETED", "at": "2026-09-20T10:00:00Z"}],
        "pending_decision": "外部窗口写入的一段",
    }
    (root / "workflow" / "runs" / "RUN-EP02-U09.json").write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")

    index = run_index.load_index(root)
    assert index["runs"] == []
    index = run_index.sync_index(root, index)
    assert [r["run_id"] for r in index["runs"]] == ["RUN-EP02-U09"]
    assert index["active_run_id"] == "RUN-EP02-U09"


def test_overview_separates_not_started_from_running(tmp_path):
    root = _make_project(tmp_path)
    started = orchestrator.start(None, CHAIN, "RUN-U01", "C1", project_root=root, segment="U01")
    orchestrator.advance(started, _handlers(), _approvals())
    orchestrator.start(None, CHAIN, "RUN-U02", "C1", project_root=root, segment="U02")

    view = run_server.current_view(root)
    assert view["counts"]["running"] == 1
    assert view["counts"]["not_started"] == 1
    active = next(r for r in view["runs"] if r["active"])
    assert active["run_id"] == "RUN-U01"


def test_server_routes_serve_live_data(tmp_path):
    root = _make_project(tmp_path)
    state = orchestrator.start(None, CHAIN, "RUN-U01", "C1", project_root=root,
                               segment="U01", segment_title="B-2A（物理格斗）")
    orchestrator.advance(state, _handlers(), _approvals())

    httpd = run_server.serve(root, port=0, open_browser=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        page = urllib.request.urlopen(f"{base}/", timeout=10).read().decode("utf-8")
        assert "B-2A（物理格斗）" in page
        assert "立即刷新" in page
        assert "自动刷新" in page

        data = json.loads(urllib.request.urlopen(f"{base}/data", timeout=10).read().decode("utf-8"))
        assert data["runs"][0]["run_id"] == "RUN-U01"

        segment = urllib.request.urlopen(f"{base}/run/RUN-U01", timeout=10).read().decode("utf-8")
        assert "short-drama-image-generator" in segment
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_reports_unknown_run_with_404(tmp_path):
    root = _make_project(tmp_path)
    orchestrator.start(None, CHAIN, "RUN-U01", "C1", project_root=root, segment="U01")
    httpd = run_server.serve(root, port=0, open_browser=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/run/RUN-NOPE", timeout=10)
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_refuses_a_project_without_runs(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    try:
        run_server.serve(root, port=0, open_browser=False)
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert "run_index.json" in str(exc)
