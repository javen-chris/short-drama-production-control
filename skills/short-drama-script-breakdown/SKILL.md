---
name: short-drama-script-breakdown
description: Convert a confirmed short-drama script segment into ScriptBreakdown, ShotUnit, and ProductionUnit records while preserving the approved story and separating narrative shots from model-generation units.
---

# Script breakdown

Read the confirmed script and `<PROTOCOL_ROOT>\09_脚本优化与分镜拆解规范_v3.0.md`. Quote source line/paragraph IDs in the evidence; do not silently rewrite confirmed plot, dialogue, relationships, world rules, or assets.

Before handing off, apply the protocol's five creative checks (hook, beat causality, payoff/reversal, motivated camera choices, and video-generation feasibility). Record PASS / REVISE / UNCERTAIN with concrete timecode or shot evidence. If the task explicitly permits creative optimization, consolidate findings into at most one candidate-revision round, preserve the confirmed source, and record before/after changes with the reason. Recheck the candidate once. If blockers remain, stop with up to three specific issues and user choices; do not loop or claim independent QA PASS. For a “check only” task, report findings without rewriting.

Produce, in order:

1. `ScriptBreakdown`: hook evidence at 0–3 seconds; goal, obstacle, action, result/reversal, unresolved question; visible change points and confirmed version.
2. `ShotUnit[]`: one visual cause each, time range, purpose, viewer focus, scene and character IDs, exact speaker/dialogue, action start/end, screen direction, spatial state, causal link, risks, and source evidence.
3. `ProductionUnit[]`: group shots only when space, costume, low-risk continuous action, and speaking control are compatible. Record input/output state, hard-cut or real-tail dependency, assets, duration, and downstream relation.

Check ordered, non-overlapping time coverage; unique IDs; every shot assigned exactly once; dialogue ownership; and output-to-next-input continuity. Submit the objects to the repository schemas and chain validator. Proposed story changes go to a separate candidate document and block downstream use until approved. A self-check is not S03 review, independent QA, or user approval.

## Decision boundary

Before replacing an approved beat, dialogue, action/contact, ending or locked shot, use the decision-card process in `22_用户决策交互与版本防循环规则_v3.0.md`. A broad goal-mode or generation instruction does not approve material creative changes.
