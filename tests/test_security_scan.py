from production_control.security_scan import scan


def test_rejects_machine_specific_windows_paths(tmp_path):
    handoff = tmp_path / "docs" / "handoff.md"
    handoff.parent.mkdir()
    local_path = "D:" + chr(92) + "AIGC-Drama-Studio" + chr(92) + "episode"
    handoff.write_text(f"Open {local_path} before continuing.", encoding="utf-8")

    forward_path = "C:/Users/synthetic/project"
    forward_handoff = tmp_path / "docs" / "forward.md"
    forward_handoff.write_text(f"Open {forward_path} too.", encoding="utf-8")

    assert scan(tmp_path) == [
        "machine-specific Windows path: docs/forward.md",
        "machine-specific Windows path: docs/handoff.md",
    ]


def test_allows_documented_portable_path_placeholder(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(r"Set the root to D:\path\to\short-drama.", encoding="utf-8")

    assert scan(tmp_path) == []


def test_rejects_production_workflow_record_directories(tmp_path):
    record_dirs = (
        "runs", "qa", "qa_reports", "authorization", "authorizations",
        "budget", "budgets", "submission_receipts", "asset_snapshots",
    )
    for directory in record_dirs:
        record = tmp_path / "project" / "workflow" / directory / "record.json"
        record.parent.mkdir(parents=True)
        record.write_text("{}", encoding="utf-8")

    assert scan(tmp_path) == [
        f"production workflow data path: project/workflow/{directory}/record.json"
        for directory in sorted(record_dirs)
    ]


def test_rejects_production_run_and_provider_task_ids_in_docs(tmp_path):
    report = tmp_path / "docs" / "status.md"
    report.parent.mkdir()
    report.write_text("RUN-EP88-A7 task-123456789012", encoding="utf-8")

    assert scan(tmp_path) == [
        "production RUN identifier: docs/status.md",
        "provider task identifier: docs/status.md",
    ]


def test_allows_synthetic_run_ids_in_example_fixtures(tmp_path):
    fixture = tmp_path / "examples" / "run_state.json"
    fixture.parent.mkdir()
    fixture.write_text('{"run_id":"RUN-EP88-A7"}', encoding="utf-8")

    assert scan(tmp_path) == []
