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

from production_control import step_registry  # noqa: E402
from production_control.outcomes import OUTCOMES  # noqa: E402
from production_control.progress import UnknownStepError, append_event  # noqa: E402

#: The concrete command that fixes it, printed with every refusal.
EXAMPLE = (
    '  python tools\\append_event.py "<项目目录>" --run <RUN-ID> '
    "--step S08 --actor <模型名> --gate G5 "
    "--protocol 12_真人短剧Prompt与故事本弹性标准_v3.0.md --evidence <证据文件>"
)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="给某一段的运行轨迹追加一步记录（协议 18 号）")
    parser.add_argument("project_root", nargs="?", help="项目根目录")
    parser.add_argument("--run", help="run_id，例如 RUN-EP02-N3-A2")
    parser.add_argument("--list-steps", action="store_true",
                        help="只打印全部合法步骤（ID／Skill 名／别名／Gate／必修协议）然后退出，不写任何东西")
    parser.add_argument("--step", default="",
                        help="步骤。推荐用稳定 ID（S01–S13）；协议 Skill 名和别名也认，"
                             "大小写/连字符/少一个字母都能自动纠正")
    parser.add_argument("--skill", default="", help="（已废弃，可忽略）实际执行的 Skill；以 --step 解析结果为准")
    parser.add_argument("--protocol", action="append", default=[], help="这一步读过的协议文件（可重复）")
    parser.add_argument("--evidence", default="", help="证据文件路径（相对项目根）")
    parser.add_argument("--outcome", default="SUBMITTED_FOR_QA", choices=list(OUTCOMES),
                        help="这一步的结果；默认 SUBMITTED_FOR_QA（生产者只能提交待审，不能写 COMPLETED）")
    parser.add_argument("--actor", default="", help="实际执行这一步的模型标识，例如 gpt-5")
    parser.add_argument("--writer-model", default="", help="实际写入看板的模型；当前必须是 glm-5.3-flash")
    parser.add_argument("--gate", default="", help="这一步所属的 Gate，例如 G5")
    parser.add_argument("--reason", default="", help="暂停/异常的原因")
    parser.add_argument("--validator", default="", help="使用的校验器")
    parser.add_argument("--allow-missing-evidence", action="store_true",
                        help="确实没有本步产物时才用；默认要求 --evidence 指向的文件真实存在")
    parser.add_argument("--off-protocol", action="store_true",
                        help="明确记录一个协议链以外的辅助动作（如 skill 审计）。"
                             "不加这个参数时，无法解析的步骤名会被拒绝")
    args = parser.parse_args(argv)

    if args.list_steps:
        # A client that can ask does not need the list pasted into its prompt -
        # and the answer is always the current chain, not a stale copy of it.
        print()
        print("  协议声明的步骤（第一列 id 是连接键，填 --step 时用它最稳）")
        print("  " + "=" * 74)
        print(step_registry.format_choices())
        print()
        print("  用法示例：--step S08 --gate G5 --protocol <必修协议> --evidence <证据文件>")
        print("  大小写/连字符/别名/拼错一两个字母都会自动归位；协议外的名字会被拒绝。")
        print("  确实要记协议链以外的辅助动作：再加 --off-protocol。")
        print()
        return 0

    if not args.project_root or not args.run or not args.step:
        parser.error("需要 project_root、--run、--step（或加 --list-steps 只看清单）")

    try:
        state = append_event(
            args.project_root, args.run, step=args.step,
            skill_id=args.skill or args.step, protocol_refs=args.protocol,
            evidence=args.evidence, outcome=args.outcome, reason=args.reason,
            validator=args.validator, allow_missing_evidence=args.allow_missing_evidence,
            actor=args.actor, role="producer", writer_model=args.writer_model,
            gate=args.gate,
            off_protocol=args.off_protocol,
        )
    except UnknownStepError as exc:
        print()
        print("=" * 70)
        print(f"❌ 步骤名无法识别：{args.step}")
        print("=" * 70)
        print(exc)
        print()
        print("照着这个格式改：")
        print(EXAMPLE)
        print()
        return 2
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"失败：{exc}")
        return 1

    canonical = (state.get("events") or [{}])[-1]
    if canonical.get("step_matched_fuzzy"):
        resolved = step_registry.resolve(args.step).step
        print()
        print(f"⚠ 你写的是「{args.step}」，已按最接近的协议步骤记录为 "
              f"{resolved.id} {resolved.skill}（相似度 {canonical['step_matched_fuzzy']}）。")
        print("  下次直接用稳定 ID 就不会有歧义。")

    pipeline = state.get("pipeline") or []
    done = len([s for s in pipeline if s in set(state.get("completed_steps", []))])
    print(f"已记录：{canonical.get('step')}  [{args.outcome}]"
          + (f"   （ID {canonical['step_id']}）" if canonical.get("step_id") else ""))
    print(f"进度：{done}/{len(pipeline)} 步 · 状态：{state.get('status')} · 当前步骤：{state.get('current_step') or '-'}")
    if state.get("pending_decision"):
        print(f"等待决定：{state['pending_decision']}")
    if canonical.get("off_protocol"):
        print()
        print(f"⚠ 这是一个协议链外的辅助记录（{canonical.get('step')}）。")
        print("  它会显示在看板的「链外」区，不会让任何 G 步骤前进。")
    print("已提交待审。这一步要显示为「通过」，必须由另一个模型的 QA 出结论：")
    print(f"  python tools/qa_verdict.py \"{args.project_root}\" --run {args.run} "
          f"--step {canonical.get('step_id') or args.step} --qa-actor <另一个模型> --verdict pass"
          + (f" --gate {args.gate}" if args.gate else "")
          + (f" --evidence {args.evidence}" if args.evidence else ""))
    print("刷新运行总表页面即可看到变化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
