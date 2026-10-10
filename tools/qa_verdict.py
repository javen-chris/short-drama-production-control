r"""Record an independent routed GPT QA verdict. This is the only pass door.

The producing model has no trace-write permission. The routed GPT QA model
records producer handoffs and its own verdict. Model-name arguments are claims,
not cryptographic identity proof.

    python tools/qa_verdict.py <项目目录> --run RUN-EP-EXAMPLE-A1 \
        --step short-drama-prompt-compiler --gate G5 \
        --execution-model gpt-5.6-luna --qa-actor gpt-5.6-terra \
        --task-id EP-EXAMPLE-A1 --version v2 --qa-level C --elapsed-seconds 42 \
        --conclusion PASS --artifact-evidence workflow/EP-EXAMPLE_A1_prompt_v2.md \
        --evidence workflow/qa/EP-EXAMPLE_A1_prompt_review_v2.md --next-step 继续G6授权检查

    python tools/qa_verdict.py <项目目录> --run RUN-EP-EXAMPLE-A1 \
        --step short-drama-prompt-compiler --gate G5 \
        --execution-model gpt-5.6-luna --qa-actor gpt-5.6-terra \
        --task-id EP-EXAMPLE-A1 --version v2 --qa-level C --elapsed-seconds 42 \
        --conclusion FAIL --artifact-evidence workflow/EP-EXAMPLE_A1_prompt_v2.md \
        --evidence workflow/qa/EP-EXAMPLE_A1_prompt_review.md \
        --reason "角色一致性不合格：小烬面部漂移"

    # 看某个 Gate 现在的 QA 状态（只读，不写）
    python tools/qa_verdict.py <项目目录> --run RUN-EP-EXAMPLE-A1 --status
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control import qa_policy, run_index, step_audit, step_registry  # noqa: E402
from production_control.progress import UnknownStepError, append_event  # noqa: E402

CONCLUSIONS = {
    "PASS": "COMPLETED",
    "FAIL": "FAILED",
    "CONDITIONAL": "WAITING_APPROVAL",
    "TIMEOUT": "WAITING_APPROVAL",
}


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

    parser = argparse.ArgumentParser(description="由路由选中的 GPT QA 模型独立审查并写入结论")
    parser.add_argument("project_root", nargs="?", help="项目根目录")
    parser.add_argument("--run", default="", help="run_id，例如 RUN-EP-EXAMPLE-A1")
    parser.add_argument("--list-steps", action="store_true",
                        help="只打印全部合法步骤（含 ID）然后退出，不写任何东西")
    parser.add_argument("--step", default="",
                        help="被 QA 的步骤。推荐用稳定 ID（S01–S13）；与生产提交的步骤按解析结果对齐，"
                             "拼写略有出入也会自动归位")
    parser.add_argument("--gate", default="", help="这一步属于哪个 Gate，例如 G5")
    parser.add_argument("--execution-model", default="", help="生产提交中记录的实际执行模型")
    parser.add_argument("--qa-actor", "--qa-model", dest="qa_actor", default="",
                        help="实际执行 QA 并写入看板的 GPT 模型")
    parser.add_argument("--task-id", default="", help="任务标识")
    parser.add_argument("--version", default="", help="被审计产物版本")
    parser.add_argument("--qa-level", default="", choices=["A", "B", "C", "FINAL"])
    parser.add_argument("--artifact-evidence", default="",
                        help="被审计产物路径（本次版本）；由 QA 写入提交事件")
    parser.add_argument("--affected-file", action="append", default=[],
                        help="本次修改/审查涉及的文件，可重复")
    parser.add_argument("--elapsed-seconds", type=int, default=None, help="实际 QA 耗时秒数")
    parser.add_argument("--conclusion", default="", choices=sorted(CONCLUSIONS),
                        help="PASS / FAIL / CONDITIONAL / TIMEOUT")
    parser.add_argument("--verdict", default="", choices=["pass", "fail"], help="旧参数兼容")
    parser.add_argument("--issue-id", default="", help="仅同版本问题复核使用的稳定问题 ID")
    parser.add_argument("--attempt", type=int, default=1, help="本版本本等级 QA 次数；同问题复核为 2")
    parser.add_argument("--blocking-issue", action="append", default=[], help="阻塞项，可重复")
    parser.add_argument("--next-step", default="", help="精确下一步")
    parser.add_argument("--evidence", default="", help="QA 报告文件（相对项目根）")
    parser.add_argument('--qa-invocation-evidence', default='', help='最终包 QA 客户端启动/会话/完成记录')
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

    conclusion = args.conclusion or (args.verdict.upper() if args.verdict else "")
    if not (args.step and conclusion and args.qa_actor and args.execution_model):
        parser.error("必须提供 --step、--conclusion、--execution-model、--qa-actor")
    if not all((args.task_id, args.version, args.qa_level, args.artifact_evidence, args.affected_file)) or args.elapsed_seconds is None:
        parser.error("QA 写入必须提供 --task-id、--version、--qa-level、--elapsed-seconds、--artifact-evidence 和 --affected-file")
    if not args.next_step:
        parser.error("QA 记录必须提供 --next-step；无下一步时填写‘停止并等待用户’")
    if conclusion == "FAIL" and not (args.issue_id and args.blocking_issue):
        parser.error("FAIL 必须至少提供一个 --blocking-issue 和稳定的 --issue-id")
    if args.qa_level == "A" and args.elapsed_seconds > 180:
        conclusion = "TIMEOUT"
    if conclusion == "TIMEOUT" and not args.issue_id:
        args.issue_id = "TIMEOUT"

    state_path = run_index.resolve_run_path(args.project_root, args.run)
    try:
        route_contract = json.loads(state_path.read_text(encoding='utf-8')).get('execution_contract') or {}
    except (OSError, ValueError):
        route_contract = {}
    allowed, why = qa_policy.qa_model_allowed(
        args.gate, args.qa_actor, execution_model=args.execution_model,
        final_packet=bool(route_contract.get('final_packet_qa_required'))
    )
    if not allowed:
        print(f"失败：{why}")
        return 1

    try:
        resolution = step_registry.resolve(args.step)
        canonical_step = resolution.step.skill if resolution.ok and resolution.step else args.step
        run_file = run_index.resolve_run_path(args.project_root, args.run)
        if not run_file.is_file():
            raise FileNotFoundError(f"没有找到轨迹文件：{run_file}")
        run_state = json.loads(run_file.read_text(encoding="utf-8"))
        matching_submission = next((event for event in reversed(run_state.get("events") or [])
                                    if event.get("step") == canonical_step
                                    and (event.get("role") or qa_policy.PRODUCER) == qa_policy.PRODUCER
                                    and event.get("version") == args.version
                                    and event.get("task_id") == args.task_id
                                    and event.get("qa_level") == args.qa_level
                                    and (event.get("writer_model") or "").strip().lower() == args.qa_actor.strip().lower()), None)
        if matching_submission and sorted(matching_submission.get("affected_files") or []) != sorted(args.affected_file):
            raise ValueError("QA_SCOPE_MISMATCH：受影响文件清单必须与提交记录一致。")
        if matching_submission is None:
            append_event(
                args.project_root, args.run, step=canonical_step, skill_id=canonical_step,
                protocol_refs=args.protocol, evidence=args.artifact_evidence,
                outcome="SUBMITTED_FOR_QA", actor=args.execution_model, role="producer",
                gate=args.gate, writer_model=args.qa_actor,
                task_id=args.task_id, version=args.version, qa_level=args.qa_level,
                affected_files=args.affected_file,
            )
        elif (matching_submission.get("actor") or "").strip().lower() != args.execution_model.strip().lower():
            raise ValueError(
                f"QA_EXECUTION_MODEL_MISMATCH：当前版本提交记录来自 {matching_submission.get('actor') or '未记录'}，"
                f"命令声明为 {args.execution_model}。"
            )
        append_event(
            args.project_root, args.run, step=args.step, skill_id=args.step,
            protocol_refs=args.protocol, evidence=args.evidence,
            outcome=CONCLUSIONS[conclusion], reason=args.reason,
            actor=args.qa_actor, role="qa", gate=args.gate,
            writer_model=args.qa_actor,
            task_id=args.task_id, version=args.version, qa_level=args.qa_level,
            qa_conclusion=conclusion, elapsed_seconds=args.elapsed_seconds,
            execution_model=args.execution_model, issue_id=args.issue_id,
            qa_attempt=args.attempt, blocking_issues=args.blocking_issue,
            next_step=args.next_step, affected_files=args.affected_file,
            allow_missing_evidence=conclusion == "TIMEOUT",
            qa_invocation_evidence=args.qa_invocation_evidence,
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
              "--step S08 --gate G5 --execution-model <执行模型> --qa-actor <路由QA模型> "
              "--task-id <任务ID> --version <版本> --qa-level <A/B/C/FINAL> "
              "--elapsed-seconds <秒> --conclusion <结论> --artifact-evidence <产物> "
              "--evidence <QA报告> --next-step <下一步>")
        print()
        return 2
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"失败：{exc}")
        return 1

    print(f"已记录 QA 结论：{args.step} → {conclusion}（QA/写入模型 {args.qa_actor}）")
    if conclusion == "FAIL":
        print("这一步没有通过。按协议，未通过 QA 不得进入下一步；"
              "先合并问题统一修订、递增版本，再按相同等级复核一次。")
    elif conclusion in {"CONDITIONAL", "TIMEOUT"}:
        print("该结论不会标绿，也不会推进正式通过状态；按阻塞信息处理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
