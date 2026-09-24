r"""Record one step of a run trace with a single command (protocol 18).

This is the *producing* model's entry point. It can submit work for review; it
cannot declare that work passed. A producer writing COMPLETED is refused with
WRITE_AUTHORITY_VIOLATION, because the only way a step may be recorded as
passed is for a different model to say so through tools/qa_verdict.py.

    python tools/append_event.py <项目目录> --run RUN-EP03-A1 \
        --step short-drama-prompt-compiler --actor gpt-5 \
        --gate G5 \
        --protocol 12_真人短剧Prompt与故事本弹性标准_v3.0.md \
        --evidence workflow/EP03_A1_prompt_v1.md
    # 默认 outcome 即 SUBMITTED_FOR_QA（提交待审）

    # 需要用户决定：
    python tools/append_event.py <项目目录> --run RUN-EP03-A1 \
        --step short-drama-prompt-compiler --actor gpt-5 \
        --outcome WAITING_APPROVAL --reason "Prompt 与资产绑定待你确认"

    # QA 由另一个模型出结论（不是这条命令）：
    python tools/qa_verdict.py <项目目录> --run RUN-EP03-A1 \
        --step short-drama-prompt-compiler --gate G5 \
        --qa-actor claude-4.5 --verdict pass \
        --evidence workflow/EP03_A1_prompt_v1.md
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control.outcomes import OUTCOMES  # noqa: E402
from production_control.progress import append_event  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="给某一段的运行轨迹追加一步记录（协议 18 号）")
    parser.add_argument("project_root", help="项目根目录")
    parser.add_argument("--run", required=True, help="run_id，例如 RUN-EP02-N3-A2")
    parser.add_argument("--step", required=True, help="这一步的步骤名（通常是 Skill 名）")
    parser.add_argument("--skill", default="", help="实际执行的 Skill（默认同 --step）")
    parser.add_argument("--protocol", action="append", default=[], help="这一步读过的协议文件（可重复）")
    parser.add_argument("--evidence", default="", help="证据文件路径（相对项目根）")
    parser.add_argument("--outcome", default="SUBMITTED_FOR_QA", choices=list(OUTCOMES),
                        help="这一步的结果；默认 SUBMITTED_FOR_QA（生产者只能提交待审，不能写 COMPLETED）")
    parser.add_argument("--actor", default="", help="执行这一步的模型标识，例如 gpt-5")
    parser.add_argument("--gate", default="", help="这一步所属的 Gate，例如 G5")
    parser.add_argument("--reason", default="", help="暂停/异常的原因")
    parser.add_argument("--validator", default="", help="使用的校验器")
    parser.add_argument("--allow-missing-evidence", action="store_true",
                        help="确实没有本步产物时才用；默认要求 --evidence 指向的文件真实存在")
    args = parser.parse_args(argv)

    try:
        state = append_event(
            args.project_root, args.run, step=args.step,
            skill_id=args.skill or args.step, protocol_refs=args.protocol,
            evidence=args.evidence, outcome=args.outcome, reason=args.reason,
            validator=args.validator, allow_missing_evidence=args.allow_missing_evidence,
            actor=args.actor, role="producer", gate=args.gate,
        )
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"失败：{exc}")
        return 1

    pipeline = state.get("pipeline") or []
    done = len([s for s in pipeline if s in set(state.get("completed_steps", []))])
    print(f"已记录：{args.step}  [{args.outcome}]")
    print(f"进度：{done}/{len(pipeline)} 步 · 状态：{state.get('status')} · 当前步骤：{state.get('current_step') or '-'}")
    if state.get("pending_decision"):
        print(f"等待决定：{state['pending_decision']}")
    print("已提交待审。这一步要显示为「通过」，必须由另一个模型的 QA 出结论：")
    print(f"  python tools/qa_verdict.py \"{args.project_root}\" --run {args.run} "
          f"--step {args.step} --qa-actor <另一个模型> --verdict pass"
          + (f" --gate {args.gate}" if args.gate else "")
          + (f" --evidence {args.evidence}" if args.evidence else ""))
    print("刷新运行总表页面即可看到变化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
