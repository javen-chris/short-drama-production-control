---
name: short-drama-script-breakdown
description: Convert a confirmed short-drama script segment into ScriptBreakdown, ShotUnit, and ProductionUnit records while preserving the approved story and separating narrative shots from model-generation units.
---

# Script breakdown

Read the confirmed script and `D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议\09_脚本优化与分镜拆解规范.md`. Quote source line/paragraph IDs in the evidence; do not silently rewrite confirmed plot, dialogue, relationships, world rules, or assets.

Produce, in order:

1. `ScriptBreakdown`: hook evidence at 0–3 seconds; goal, obstacle, action, result/reversal, unresolved question; visible change points and confirmed version.
2. `ShotUnit[]`: one visual cause each, time range, purpose, viewer focus, scene and character IDs, exact speaker/dialogue, action start/end, screen direction, spatial state, causal link, risks, and source evidence.
3. `ProductionUnit[]`: group shots only when space, costume, low-risk continuous action, and speaking control are compatible. Record input/output state, hard-cut or real-tail dependency, assets, duration, and downstream relation.

Check ordered, non-overlapping time coverage; unique IDs; every shot assigned exactly once; dialogue ownership; and output-to-next-input continuity. Submit the objects to the repository schemas and chain validator. Proposed story changes go to a separate candidate document and block downstream use until approved.
