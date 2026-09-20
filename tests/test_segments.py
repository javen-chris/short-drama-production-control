import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from production_control import orchestrator, run_index, run_server

CHAIN = {"steps": [{"skill": "short-drama-production-router", "after": []}]}


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "workflow").mkdir(parents=True)
    return root


def _serve(root: Path):
    httpd = run_server.serve(root, port=0, open_browser=False)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def test_segment_list_round_trips_to_disk(tmp_path):
    root = _project(tmp_path)
    document = {
        "project": "DRAGONTRAIN-EP02", "series": "龙骨列车", "episode": "EP02",
        "segments": [
            {"segment": "U01", "title": "B-2A（物理格斗）", "note": "开门即打"},
            {"segment": "U02", "title": "B-3D（人物躲避爆炸）", "note": ""},
        ],
    }
    run_index.save_segments(root, document)
    loaded = run_index.load_segments(root)
    assert [s["segment"] for s in loaded["segments"]] == ["U01", "U02"]
    assert loaded["segments"][0]["title"] == "B-2A（物理格斗）"
    assert loaded["episode"] == "EP02"


def test_filled_in_segments_appear_as_not_started_rows(tmp_path):
    """No demo data: what the user types is what the overview shows."""
    root = _project(tmp_path)
    run_index.save_segments(root, {
        "project": "P", "series": "龙骨列车", "episode": "EP02",
        "segments": [{"segment": f"U{i:02d}", "title": f"B-{i}A（示例动作{i}）"} for i in range(1, 21)],
    })
    view = run_server.current_view(root)
    assert view["counts"]["total"] == 20
    assert view["counts"]["not_started"] == 20
    first = view["runs"][0]
    assert first["segment"] == "U01"
    assert first["segment_title"] == "B-1A（示例动作1）"


def test_duplicate_segment_codes_are_rejected(tmp_path):
    root = _project(tmp_path)
    try:
        run_index.save_segments(root, {"segments": [{"segment": "U01"}, {"segment": "U01"}]})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "duplicate" in str(exc)


def test_segment_without_code_is_rejected(tmp_path):
    root = _project(tmp_path)
    try:
        run_index.save_segments(root, {"segments": [{"title": "没有段号"}]})
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "needs a code" in str(exc)


def test_agent_adopts_the_name_the_user_entered(tmp_path):
    """The whole point: one name for a segment, agreed by page and agent."""
    root = _project(tmp_path)
    run_index.save_segments(root, {
        "project": "P", "episode": "EP02",
        "segments": [{"segment": "U05", "title": "B-3C（反击）"}],
    })
    state = orchestrator.start(None, CHAIN, "RUN-EP02-U05", "C1", project_root=root, segment="U05")
    assert state["segment_title"] == "B-3C（反击）"
    index = json.loads((root / "workflow" / "run_index.json").read_text(encoding="utf-8"))
    row = next(r for r in index["runs"] if r["run_id"] == "RUN-EP02-U05")
    assert row["segment_title"] == "B-3C（反击）"


def test_existing_run_is_not_renamed_away_from_the_list(tmp_path):
    root = _project(tmp_path)
    state = orchestrator.start(None, CHAIN, "RUN-EP02-U01", "C1", project_root=root,
                               segment="U01", segment_title="旧名字")
    orchestrator.advance(state, {"short-drama-production-router": lambda: {
        "skill_id": "short-drama-production-router",
        "protocol_refs": [{"path": "00_自动化生产唯一入口_v3.0.md"}],
        "evidence": "e.json",
    }}, {"short-drama-production-router"})
    run_index.save_segments(root, {"project": "P", "episode": "EP02",
                                   "segments": [{"segment": "U01", "title": "B-2A（物理格斗）"}]})
    view = run_server.current_view(root)
    row = next(r for r in view["runs"] if r["segment"] == "U01")
    assert row["segment_title"] == "B-2A（物理格斗）"  # the user's list wins on naming
    assert row["status"] == "COMPLETED"  # the trace wins on state


def test_page_can_save_the_list_over_http(tmp_path):
    root = _project(tmp_path)
    orchestrator.start(None, CHAIN, "RUN-EP02-U01", "C1", project_root=root, segment="U01")
    httpd, port = _serve(root)
    base = f"http://127.0.0.1:{port}"
    try:
        payload = json.dumps({
            "project": "DRAGONTRAIN-EP02", "series": "龙骨列车", "episode": "EP02",
            "segments": [{"segment": "U01", "title": "B-2A（物理格斗）"}, {"segment": "U02", "title": "B-2B（近身压制）"}],
        }).encode("utf-8")
        request = urllib.request.Request(f"{base}/api/segments", data=payload,
                                        headers={"Content-Type": "application/json"}, method="POST")
        response = json.loads(urllib.request.urlopen(request, timeout=10).read().decode("utf-8"))
        assert response["ok"] is True

        # The saved list is on disk and shows up in the overview immediately.
        saved = json.loads((root / "workflow" / "segments.json").read_text(encoding="utf-8"))
        assert len(saved["segments"]) == 2
        view = json.loads(urllib.request.urlopen(f"{base}/data", timeout=10).read().decode("utf-8"))
        titles = {r["segment"]: r["segment_title"] for r in view["runs"]}
        assert titles["U02"] == "B-2B（近身压制）"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_page_reports_a_bad_list_instead_of_writing_it(tmp_path):
    root = _project(tmp_path)
    orchestrator.start(None, CHAIN, "RUN-EP02-U01", "C1", project_root=root, segment="U01")
    httpd, port = _serve(root)
    try:
        payload = json.dumps({"segments": [{"segment": "U01"}, {"segment": "U01"}]}).encode("utf-8")
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/segments", data=payload,
                                        headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(request, timeout=10)
            raise AssertionError("expected 400")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            body = json.loads(exc.read().decode("utf-8"))
            assert "duplicate" in body["error"]
        assert not (root / "workflow" / "segments.json").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_page_contains_the_editor_and_static_page_does_not(tmp_path):
    root = _project(tmp_path)
    orchestrator.start(None, CHAIN, "RUN-EP02-U01", "C1", project_root=root, segment="U01")
    httpd, port = _serve(root)
    try:
        live = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read().decode("utf-8")
        assert "保存段清单" in live
        assert "/api/segments" in live
    finally:
        httpd.shutdown()
        httpd.server_close()

    from production_control.run_report import render_project_html

    static = render_project_html(run_server.current_view(root), live=False)
    assert "保存段清单" not in static
    assert "静态快照无法写回磁盘" in static
