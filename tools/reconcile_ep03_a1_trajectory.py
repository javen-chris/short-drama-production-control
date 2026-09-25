"""One-off: reconcile RUN-EP03-A1.json against the project's own state.

Why this exists
---------------
On 2026-09-24 22:28 the trajectory recorded G5-prompt as COMPLETED and
G6-pre-submit as BLOCKED. Since then the user changed the route twice
(storyboard v1-v5 retired, then a single first-frame contract), and the
project's own `workflow/project_state.json` now says:

    "G5_video_prompt": "BLOCKED_UNTIL_USER_APPROVES_FIRST_FRAME"
    "禁止进入G5/G6"

So the trajectory's G5 verdict is not merely old, it is *wrong in the unsafe
direction*: a reader of the trace would conclude the prompt is settled and only
the adapter is missing. Reality is that the route changed underneath it and G5
must be redone.

This script does NOT delete history. It keeps every event, and for the two
affected steps it:
  - records the original outcome under `superseded_outcome` / `superseded_reason`
  - demotes the outcome to INVALIDATED (G5) / stays BLOCKED (G6)
  - adds a `correction` block with when, why, and which file is authoritative

Idempotent: re-running on an already-corrected file is a no-op.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

RUN = Path(r"D:\AIGC-Drama-Studio\龙骨列车\龙骨列车EP03\workflow\runs\RUN-EP03-A1.json")

CORRECTIONS = {
    "G5-prompt": {
        "new_outcome": "INVALIDATED",
        "reason": (
            "判定失效：本条记录于 2026-09-24 22:28 判为 COMPLETED，当时依据的是"
            "「故事本 + 分镜提示词」路线。此后用户先后裁定①故事本 v1–v5 全部退出生产主线，"
            "②改走「唯一首帧空间合同」路线。生产前 QA（14:40）与首帧视觉 QA（14:42）"
            "均在本条记录之后产生，说明 G5 的输入已变。"
            "workflow/project_state.json 明示 G5 为 "
            "BLOCKED_UNTIL_USER_APPROVES_FIRST_FRAME。"
            "故 G5 不成立，须在首帧确认后重做。"
        ),
    },
    "G6-pre-submit": {
        "new_outcome": "BLOCKED",
        "reason": (
            "确认阻断（与原记录一致，此处补注最新依据）：G6 不仅受 LibTV Token 与资产绑定阻断，"
            "更受上游 G5 判定失效阻断。在 G5 重做并取得独立 QA 通过之前，G6 不得进入。"
        ),
    },
}


def main() -> int:
    state = json.loads(RUN.read_text(encoding="utf-8"))
    events = state.get("events") or []
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    changed = 0
    for event in events:
        step = event.get("step")
        rule = CORRECTIONS.get(step)
        if not rule or event.get("correction"):
            continue
        event["superseded_outcome"] = event.get("outcome", "")
        event["superseded_reason"] = event.get("reason", "")
        event["outcome"] = rule["new_outcome"]
        event["reason"] = rule["reason"]
        event["correction"] = {
            "at": stamp,
            "authority": "workflow/project_state.json",
            "authority_status": "FIRST_FRAME_QA_PASS_WAITING_USER_APPROVAL",
            "why": "轨迹结论与现实冲突；以 project_state 为准回溯修正（用户裁定 2026-09-25）",
            "note": "事件未被删除；原判定保存在 superseded_outcome。",
        }
        changed += 1

    if not changed:
        print("无需修改：修正已存在。")
        return 0

    # completed_steps must not keep a step the events now disown.
    demoted = {s for s, r in CORRECTIONS.items() if r["new_outcome"] != "COMPLETED"}
    before = list(state.get("completed_steps") or [])
    after = [s for s in before if s not in demoted]
    state["completed_steps"] = after

    state["correction_note"] = (
        f"2026-09-25 回溯修正：{changed} 条事件判定与 project_state.json 冲突，已降级并保留原判定。"
        f"completed_steps 移除：{sorted(set(before) - set(after))}。"
        "依据用户裁定：以 project_state 为准。"
    )
    state["updated_at"] = stamp

    shutil.copy2(RUN, RUN.with_suffix(".json.pre_correction_tmp"))
    RUN.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已修正 {changed} 条事件。")
    print("completed_steps:", before, "->", after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
