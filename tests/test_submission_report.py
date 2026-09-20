import json

import pytest

from production_control.submission_report import can_submit, validate_submission, write_report

GOOD_ASSET = {"path": "场景资产/书房.png", "role": "scene_master", "qa_status": "PASS", "sha256": "a" * 64}


def good_report(**overrides):
    report = {
        "unit_id": "U03",
        "run_id": "RUN-EP02-U03",
        "platform": "runninghub",
        "api_mode": "api",
        "model": "rh_h3",
        "model_version": "v2",
        "duration_seconds": 5,
        "resolution": "1280x720",
        "fps": 24,
        "aspect_ratio": "16:9",
        "reference_assets": [dict(GOOD_ASSET), {"path": "人物资产库/女主/脸.png", "role": "face_master", "qa_status": "PASS"}],
        "prompt": "中近景，女主在书桌右侧接起手机",
        "cost_estimate_cny": 2.0,
        "authorization": {"scope": "test_submission", "source": "用户：QA 检查确认通过，可生视频", "max_submissions": 1, "submission_index": 1},
        "qa_gate": {"g5_review": "PASS", "preflight": "PASS", "assets_all_pass": True},
        "confirmed": True,
        "confirmed_at": "2026-09-20T22:30:00+08:00",
        "confirmed_via": "用户在会话中确认",
    }
    report.update(overrides)
    return report


def test_a_complete_report_may_submit():
    allowed, reasons = can_submit(good_report())
    assert allowed, reasons


def test_empty_asset_list_is_blocked():
    """The 2026-09-20 incident: submitted with nothing attached."""
    allowed, reasons = can_submit(good_report(reference_assets=[]))
    assert not allowed
    assert any("reference_assets is empty" in r for r in reasons)


def test_missing_asset_list_is_blocked():
    report = good_report()
    del report["reference_assets"]
    allowed, reasons = can_submit(report)
    assert not allowed
    assert any("reference_assets is missing" in r for r in reasons)


def test_asset_without_qa_pass_is_blocked():
    report = good_report(reference_assets=[{"path": "场景资产/书房.png", "role": "scene_master", "qa_status": "NOT_CHECKED"}])
    allowed, reasons = can_submit(report)
    assert not allowed
    assert any("qa_status must be PASS" in r for r in reasons)


def test_asset_file_must_exist_on_disk(tmp_path):
    (tmp_path / "场景资产").mkdir()
    (tmp_path / "场景资产" / "书房.png").write_bytes(b"png")
    report = good_report(reference_assets=[dict(GOOD_ASSET)])
    allowed, reasons = can_submit(report, tmp_path)
    assert allowed, reasons

    report = good_report(reference_assets=[{"path": "场景资产/不存在.png", "role": "scene_master", "qa_status": "PASS"}])
    allowed, reasons = can_submit(report, tmp_path)
    assert not allowed
    assert any("does not exist" in r for r in reasons)


def test_asset_hash_is_verified_when_requested(tmp_path):
    target = tmp_path / "场景资产"
    target.mkdir()
    (target / "书房.png").write_bytes(b"real-content")
    report = good_report(reference_assets=[dict(GOOD_ASSET)])
    allowed, reasons = can_submit(report, tmp_path, verify_hashes=True)
    assert not allowed
    assert any("sha256 does not match" in r for r in reasons)


def test_incomplete_parameters_are_blocked():
    allowed, reasons = can_submit(good_report(duration_seconds=0, resolution=""))
    assert not allowed
    assert any("duration_seconds" in r for r in reasons)
    assert any("resolution" in r for r in reasons)


def test_prompt_is_required():
    allowed, reasons = can_submit(good_report(prompt=""))
    assert not allowed
    assert any("prompt is required" in r for r in reasons)


def test_qa_only_scope_forbids_submitting():
    allowed, reasons = can_submit(good_report(authorization={"scope": "qa_only", "source": "只要求跑到QA"}))
    assert not allowed
    assert any("qa_only" in r for r in reasons)


def test_authorized_but_unconfirmed_is_blocked():
    allowed, reasons = can_submit(good_report(confirmed=False))
    assert not allowed
    assert any("confirmed must be true" in r for r in reasons)


def test_authorization_source_is_mandatory():
    allowed, reasons = can_submit(good_report(authorization={"scope": "test_submission", "source": ""}))
    assert not allowed
    assert any("authorization.source" in r for r in reasons)


def test_exceeding_the_authorized_submission_count_is_blocked():
    allowed, reasons = can_submit(good_report(authorization={"scope": "test_submission", "source": "一次测试", "max_submissions": 1, "submission_index": 2}))
    assert not allowed
    assert any("exceeds max_submissions" in r for r in reasons)


def test_gate_failures_block():
    allowed, reasons = can_submit(good_report(qa_gate={"g5_review": "FAIL", "preflight": "PASS", "assets_all_pass": True}))
    assert not allowed
    assert any("g5_review must be PASS" in r for r in reasons)


def test_ui_manual_submission_is_held_to_the_same_rule():
    """Clicking generate in a web UI is also a submission."""
    allowed, reasons = can_submit(good_report(platform="xiaoyunque", api_mode="ui_manual", reference_assets=[]))
    assert not allowed
    assert any("reference_assets is empty" in r for r in reasons)


def test_report_is_append_only(tmp_path):
    target = tmp_path / "workflow" / "submission_reports" / "U03_V1.json"
    write_report(target, good_report())
    assert target.is_file()
    with pytest.raises(FileExistsError):
        write_report(target, good_report())


def test_report_round_trips_through_json(tmp_path):
    target = tmp_path / "reports" / "U03_V1.json"
    write_report(target, good_report())
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert validate_submission(loaded) == []
