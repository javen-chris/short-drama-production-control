r"""Record a QA verdict. This is the only door a step can pass through.

The producing model may submit its work (tools/append_event.py), but it may not
declare that work passed. Only this command can, and it refuses to run unless a
model other than the producer is named as the reviewer, and that model is
allowed to review this Gate by capabilities/qa_policy.json.

    python tools/qa_verdict.py <项目目录> --run RUN-EP03-A1 \
        --step short-drama-prompt-compiler --gate G5 \
        --qa-actor claude-4.5 --verdict pass \
        --evidence workflow/EP03_A1_prompt_v1.md

    python tools/qa_verdict.py <项目目录> --run RUN-EP03-A1 \
        --step short-drama-prompt-compiler --gate G5 \
        --qa-actor claude-4.5 --verdict fail \
        --evidence workflow/qa/EP03_A1_prompt_review.md \
        --reason "角色一致性不合格：小烬面部漂移"

    # 看某个 Gate 现在的 QA 状态（只读，不写）
    python tools/qa_verdict.py <项目目录> --run RUN-EP03-A1 --status
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control import qa_policy, run_index, step_audit, step_registry  # noqa: E402
from production_control.progress import UnknownStepError, append_event  # noqa: E402

VERDICTS = {"pass": "COMPLETED", "fail": "FAILED"}


def _status(root: str, run_id: str) -> int:
    run_file = run_index.resolve_run_path(root, run_id)
    if not run_file.is_file():
        print(f"找不到轨迹文件：{run_file}")
        return 1
    state = json.loads(run_file.read_text(encoding="utf-8"))
    verdict = step_audit.audit_qa_passes(state, root)
    print(f"run = {run_id}")
    print(f"  QA 通过 {verdict['passed']} / 已提交 {verdict['submitted']} / 等待 QA {verdict['awaiting']}"
          f" / QA 不通过 {verdict['failed']}")
    for row in verdict["rows"]:
        line = f"  [{row['state']}] {row['step']}"
        if row.get("producer_actor") or row.get("qa_actor"):
            line += f"  生产={row.get('producer_actor') or '-'}  QA={row.get('qa_actor') or '-'}"
        print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="由 QA 模型写入一步的 QA 结论（生产模型无权写）")
    parser.add_argument("project_root", nargs="?", help="项目根目录")
    parser.add_argument("--run", default="", help="run_id，例如 RUN-EP03-A1")
    parser.add_argument("--list-steps", action="store_true",
                        help="只打印全部合法步骤（含 ID）然后退出，不写任何东西")
    parser.add_argument("--step", default="",
                        help="被 QA 的步骤。推荐用稳定 ID（S01–S13）；与生产提交的步骤按解析结果对齐，"
                             "拼写略有出入也会自动归位")
    parser.add_argument("--gate", default="", help="这一步属于哪个 Gate，例如 G5")
    parser.add_argument("--qa-actor", default="", help="执行 QA 的模型标识，必须与生产模型不同")
    parser.add_argument("--verdict", default="", choices=sorted(VERDICTS), help="pass 或 fail")
    parser.add_argument("--evidence", default="", help="QA 报告文件（相对项目根）")
    parser.add_argument("--reason", default="", help="不通过的原因 / 说明")
    parser.add_argument("--protocol", action="append", default=[], help="QA 依据的协议文件（可重复）")
    parser.add_argument("--status", action="store_true", help="只读查看该 run 的 QA 状态，不写入")
    args = parser.parse_args(argv)

    if args.list_steps:
        print()
        print("  QA 要写哪一步，就用它的 id（--step 填这个最稳）：")
        print("  " + "=" * 74)
        print(step_registry.format_choices())
        print()
        print("  QA 的 --step 必须与生产提交时那一步一致；两侧拼写略有出入也会自动归位。")
        print()
        return 0

    if not args.project_root or not args.run:
        parser.error("需要 project_root、--run（或加 --list-steps 只看清单）")

    if args.status:
        return _status(args.project_root, args.run)

    if not (args.step and args.verdict and args.qa_actor):
        parser.error("必须提供 --step、--verdict、--qa-actor")

    allowed, why = qa_policy.qa_model_allowed(args.gate, args.qa_actor)
    if not allowed:
        print(f"失败：{why}")
        return 1

    try:
        append_event(
            args.project_root, args.run, step=args.step, skill_id=args.step,
            protocol_refs=args.protocol, evidence=args.evidence,
            outcome=VERDICTS[args.verdict], reason=args.reason,
            actor=args.qa_actor, role="qa", gate=args.gate,
            writer_model=args.qa_actor,
            allow_missing_evidence=not args.evidence,
        )
    except UnknownStepError as exc:
        print()
        print("=" * 70)
        print(f"❌ QA 的步骤名无法识别：{args.step}")
        print("=" * 70)
        print(exc)
        print()
        print("QA 的 --step 必须是生产提交时那一步。用稳定 ID 最稳：")
        print("  python tools/qa_verdict.py \"<项目目录>\" --run <RUN-ID> "
              "--step S08 --gate G5 --qa-actor <另一个模型> --verdict pass --evidence <QA报告>")
        print()
        return 2
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"失败：{exc}")
        return 1

    verdict_label = "通过" if args.verdict == "pass" else "不通过"
    print(f"已记录 QA 结论：{args.step} → {verdict_label}（QA 模型 {args.qa_actor}）")
    if args.verdict == "fail":
        print("这一步没有通过。按协议，未通过 QA 不得进入下一步；"
              "修订后必须递增 Prompt 版本并重新 QA。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
