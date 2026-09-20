r"""Record one step of a run trace with a single command (protocol 18).

    python tools/append_event.py <项目目录> --run RUN-EP02-N3-A2 \
        --step short-drama-production-router \
        --protocol 00_自动化生产唯一入口_v3.0.md \
        --protocol 核心自动化生产包/02_任务路由与Gate_v3.0.md \
        --evidence workflow/G0_上下文锁定_N3-A2.md

    # 遇到需要用户决定的情况：
    python tools/append_event.py <项目目录> --run RUN-EP02-N3-A2 \
        --step short-drama-production-qa --outcome WAITING_APPROVAL \
        --reason "G5 Prompt QA 完成，等待用户审阅后决定是否提交"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
    parser.add_argument("--outcome", default="COMPLETED",
                        choices=["COMPLETED", "WAITING_APPROVAL", "PAUSED_EXCEPTION", "BLOCKED"])
    parser.add_argument("--reason", default="", help="暂停/异常的原因")
    parser.add_argument("--validator", default="", help="使用的校验器")
    args = parser.parse_args(argv)

    try:
        state = append_event(
            args.project_root, args.run, step=args.step,
            skill_id=args.skill or args.step, protocol_refs=args.protocol,
            evidence=args.evidence, outcome=args.outcome, reason=args.reason,
            validator=args.validator,
        )
    except FileNotFoundError as exc:
        print(f"失败：{exc}")
        return 1

    pipeline = state.get("pipeline") or []
    done = len([s for s in pipeline if s in set(state.get("completed_steps", []))])
    print(f"已记录：{args.step}  [{args.outcome}]")
    print(f"进度：{done}/{len(pipeline)} 步 · 状态：{state.get('status')} · 当前步骤：{state.get('current_step') or '-'}")
    if state.get("pending_decision"):
        print(f"等待决定：{state['pending_decision']}")
    print("刷新运行总表页面即可看到变化。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
