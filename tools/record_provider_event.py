"""Record a provider submission/status fact without claiming a model QA verdict.

The evidence file must contain the provider response or an auditable API receipt.
This CLI records the supplied values; it does not authenticate the remote
provider session. Content QA remains a separate role and event type.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control.progress import append_event  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="记录 G6 平台回执事实，不写入内容 QA 结论")
    parser.add_argument("project_root")
    parser.add_argument("--run", required=True)
    parser.add_argument("--step", choices=["S11", "S12", "G6-S11", "G6-S12",
                                            "short-drama-authorized-submit", "short-drama-task-monitor"], required=True)
    parser.add_argument("--outcome", choices=["TASK_SUBMITTED", "SUBMITTED_IN_PROGRESS", "TASK_SUCCEEDED", "TASK_FAILED", "TASK_UNVERIFIED"], required=True)
    parser.add_argument("--provider", choices=["runninghub", "xiaoyunque", "libtv"], required=True)
    parser.add_argument("--provider-task-id", required=True)
    parser.add_argument("--provider-status", required=True)
    parser.add_argument("--output-url", action="append", default=[])
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--gate", default="G6")
    parser.add_argument("--evidence", required=True, help="相对项目根目录的供应商回执证据文件")
    parser.add_argument("--reason", default="", help="无法核实时写明具体异常和后续裁定")
    parser.add_argument("--elapsed-seconds", type=int, default=None, help="供应商排队/生成耗时")
    parser.add_argument("--protocol", action="append", default=[])
    args = parser.parse_args(argv)
    step = ("short-drama-authorized-submit" if args.outcome == "TASK_SUBMITTED"
            else "short-drama-task-monitor")
    try:
        state = append_event(
            args.project_root, args.run, step=step, protocol_refs=args.protocol,
            evidence=args.evidence, outcome=args.outcome, gate=args.gate, reason=args.reason,
            task_id=args.task_id, version=args.version, role="executor",
            source_adapter=args.provider, provider_task_id=args.provider_task_id,
            provider_status=args.provider_status, output_urls=args.output_url,
            elapsed_seconds=args.elapsed_seconds, elapsed_phase="provider_queue",
            validator="provider-status-evidence-recorded",
        )
    except (OSError, ValueError, PermissionError) as exc:
        print(f"失败：{exc}")
        return 1
    print(f"已记录平台事实：{args.outcome} · {args.provider} · {args.provider_task_id}")
    print(f"RUN 状态：{state.get('status')}；内容 QA 结论未改变")
    if args.outcome == "TASK_SUCCEEDED":
        for url in args.output_url:
            print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
