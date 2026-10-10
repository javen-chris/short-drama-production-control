---
name: short-drama-script-reviewer
description: Review a confirmed short-drama script and shot units for hook, beat chain, visible change points, dialogue ownership, and one-visual-cause-per-unit before prompt compilation.
---

# Short-drama Script Reviewer

Read `D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议\09_脚本优化与分镜拆解规范_v3.0.md`, the confirmed source, any separately saved candidate, and the complete objects produced by `short-drama-script-breakdown`. Review against the same five checks used by the breakdown Skill. Do not generate or repair the reviewed objects in place; do not silently rewrite confirmed plot, character relationships, world setting, or permissions.

## Required review record

For each production unit, record:

- a hook in the first 0–3 seconds;
- the beat chain: hook → goal → obstacle → action → result/reversal → unresolved question;
- at least one visible change per 3–5 seconds;
- one visual cause per shot unit;
- one explicit dialogue speaker and the post-dialogue state;
- any high-risk action that requires keyframes or a storyboard.

For every check, record `PASS / REVISE / UNCERTAIN`, the exact timecode/shot/line, the observed evidence, and why it matters. For camera choices, judge whether the framing or movement clarifies information, emotion, or action; do not fail a scene merely for using a repeated shot size when repetition is intentional. For hooks and reversals, distinguish a real story change from sound/effect/close-up emphasis alone. For generation feasibility, identify overloaded actions, unclear start/end states, space changes, speaker conflicts, and high-risk contact.

If reviewing a revised candidate, compare it with its cited source version and verify that each change addresses a recorded issue without introducing new continuity, dialogue, permission, or story conflicts. Return no more than three blocking issues first, followed by optional craft improvements. This review is a content review, not proof of a different model identity or a substitute for the separately routed production QA.

The record must be `PASS` before the Prompt Compiler can route a video prompt. `PENDING` or `FAIL` blocks provider adapters.

Also fail on uncovered or overlapping time, duplicate IDs, missing source evidence, a shot assigned to multiple production units, output/input state discontinuity without an explicit hard cut, or a production unit that combines incompatible space, costume, speaker, or high-risk contact. Store findings and evidence separately from the generated breakdown.

## Decision boundary

Report evidence and classify whether a correction stays within approved content. Do not silently select or apply a material story/action/ending/scope change. Follow `22_用户决策交互与版本防循环规则_v3.0.md` and provide decision-ready options.
