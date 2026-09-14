---
name: short-drama-script-reviewer
description: Review a confirmed short-drama script and shot units for hook, beat chain, visible change points, dialogue ownership, and one-visual-cause-per-unit before prompt compilation.
---

# Short-drama Script Reviewer

Read `D:\短剧制作核心协议\09_脚本优化与分镜拆解规范.md` and the current project's confirmed script before reviewing. This Skill may identify problems and propose candidates, but must not silently rewrite confirmed plot, character relationships, world setting, or permissions.

## Required review record

For each production unit, record:

- a hook in the first 0–3 seconds;
- the beat chain: hook → goal → obstacle → action → result/reversal → unresolved question;
- at least one visible change per 3–5 seconds;
- one visual cause per shot unit;
- one explicit dialogue speaker and the post-dialogue state;
- any high-risk action that requires keyframes or a storyboard.

The record must be `PASS` before the Prompt Compiler can route a video prompt. `PENDING` or `FAIL` blocks provider adapters.

