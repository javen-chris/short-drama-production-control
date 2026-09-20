"""Check a pre-submission report before a video generation is submitted.

Why this exists: on 2026-09-20 a generation was submitted with nothing attached -
no reference assets, incomplete parameters. The user had authorized the
generation, so authorization was not the problem; the submission content was.
Being allowed to submit is not the same as submitting something usable.

Rule 19 requires a report before every submission, on every platform, including
clicking generate in a web UI. This module is the offline check for it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Scope decides whether submitting is permitted at all.
SCOPES = {
    "qa_only": "只要求跑到生成前 QA",
    "test_submission": "授权一次测试提交",
    "full_segment": "授权本段完整生成",
    "within_budget": "授权预算内多次",
}

PLATFORMS_REQUIRING_TASK_ID = {"runninghub", "xiaoyunque", "libtv"}

PARAMETER_FIELDS = ("model", "platform", "api_mode", "duration_seconds", "resolution", "aspect_ratio")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_assets(report: dict, project_root: Path | None, verify_hashes: bool) -> list[str]:
    """The core of the incident: assets must be listed, present, and QA-passed."""
    errors: list[str] = []
    assets = report.get("reference_assets")
    if assets is None:
        return ["reference_assets is missing: list every asset the generation conditions on"]
    if not assets:
        return [
            "reference_assets is empty: submitting with nothing attached produces a video that cannot match the MASTERs"
        ]
    for index, asset in enumerate(assets):
        path = asset.get("path")
        role = asset.get("role", "?")
        if not path:
            errors.append(f"asset {index} ({role}): missing path")
            continue
        if asset.get("qa_status") != "PASS":
            errors.append(f"asset {index} ({role}): qa_status must be PASS, got {asset.get('qa_status')}")
        if project_root is not None:
            target = project_root / path
            if not target.is_file():
                errors.append(f"asset {index} ({role}): file does not exist: {path}")
            elif verify_hashes and asset.get("sha256"):
                if sha256_file(target) != asset["sha256"]:
                    errors.append(f"asset {index} ({role}): sha256 does not match the file on disk")
    return errors


def _check_parameters(report: dict) -> list[str]:
    errors: list[str] = []
    for field in PARAMETER_FIELDS:
        value = report.get(field)
        if value in (None, "", 0):
            errors.append(f"{field} is required before submitting")
    if not report.get("prompt") and not report.get("prompt_path") and not report.get("prompt_sha256"):
        errors.append("prompt is required (inline text, a path, or a sha256)")
    return errors


def _check_authorization(report: dict) -> list[str]:
    errors: list[str] = []
    authorization = report.get("authorization") or {}
    scope = authorization.get("scope")
    if scope not in SCOPES:
        errors.append(f"authorization.scope must be one of {sorted(SCOPES)}")
        return errors
    if scope == "qa_only":
        errors.append("authorization.scope is qa_only: the instruction only covered production up to QA, submitting is out of scope")
    if not authorization.get("source"):
        errors.append("authorization.source is required: record which instruction authorized this submission")
    max_submissions = authorization.get("max_submissions")
    index = authorization.get("submission_index")
    if max_submissions is not None and index is not None and index > max_submissions:
        errors.append(f"submission_index {index} exceeds max_submissions {max_submissions}")
    return errors


def _check_gate_and_confirmation(report: dict) -> list[str]:
    errors: list[str] = []
    if report.get("confirmed") is not True:
        errors.append("confirmed must be true: the user has to approve the report before submitting")
    else:
        if not report.get("confirmed_at"):
            errors.append("confirmed_at is required when confirmed is true")
        if not report.get("confirmed_via"):
            errors.append("confirmed_via is required: it must be traceable to a user message or confirmation sheet")
    gate = report.get("qa_gate") or {}
    if gate.get("g5_review") != "PASS":
        errors.append("qa_gate.g5_review must be PASS")
    if gate.get("preflight") != "PASS":
        errors.append("qa_gate.preflight must be PASS")
    if gate.get("assets_all_pass") is not True:
        errors.append("qa_gate.assets_all_pass must be true")
    return errors


def validate_submission(report: dict, project_root: str | Path | None = None, *,
                        verify_hashes: bool = False, require_assets: bool = True) -> list[str]:
    """Every reason this submission must not be sent. Empty list means it may go."""
    root = Path(project_root) if project_root else None
    errors: list[str] = []
    if not report.get("unit_id"):
        errors.append("unit_id is required")
    # Assets are the point: check them whenever they are required, and also when
    # they are present but not required (a partial list is still a list to check).
    if require_assets or report.get("reference_assets"):
        errors += _check_assets(report, root, verify_hashes)
    errors += _check_parameters(report)
    errors += _check_authorization(report)
    errors += _check_gate_and_confirmation(report)
    cost = report.get("cost_estimate_cny")
    budget = report.get("budget_cny")
    if cost is not None and budget is not None and cost > budget:
        errors.append(f"cost_estimate_cny {cost} exceeds budget_cny {budget}")
    return errors


def can_submit(report: dict, project_root: str | Path | None = None, **kwargs) -> tuple[bool, list[str]]:
    """(allowed, reasons). Reasons are non-empty whenever allowed is False."""
    errors = validate_submission(report, project_root, **kwargs)
    return (not errors, errors)


def load_report(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_report(path: str | Path, report: dict) -> Path:
    """Append-only ledger: refuse to silently overwrite an existing report."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} already exists - submission reports are append-only, use the next version")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check a pre-submission report (protocol rule 19)")
    parser.add_argument("report", help="path to submission_report json")
    parser.add_argument("--project-root", help="project root, to verify referenced assets exist")
    parser.add_argument("--verify-hashes", action="store_true", help="also recompute asset sha256")
    args = parser.parse_args()
    report = load_report(args.report)
    allowed, reasons = can_submit(report, args.project_root, verify_hashes=args.verify_hashes)
    if allowed:
        print("可以提交：报告完整，参考资产与参数齐全，确认有效")
        return 0
    print("禁止提交（原因如下）：")
    for reason in reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
