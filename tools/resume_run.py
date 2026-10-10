"""Inspect or resume an existing RUN without creating a replacement."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from production_control.resume_run import resume


def main() -> int:
    parser = argparse.ArgumentParser(description="从原 RUN 的有效证据恢复当前步骤")
    parser.add_argument("project_root")
    parser.add_argument("--run", required=True)
    parser.add_argument("--inspect", action="store_true", help="只读检查，不写恢复记录")
    args = parser.parse_args()
    try:
        result = resume(args.project_root, args.run, apply=not args.inspect)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"READY", "COMPLETED", "WAITING_QA", "WAITING_DECISION", "LEGACY_INSPECT_ONLY", "SUBMITTED_TASK_REQUIRES_QUERY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
