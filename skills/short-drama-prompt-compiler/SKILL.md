---
name: short-drama-prompt-compiler
description: Compile approved short-drama production units into provider-neutral prompts, then route direct-prompt, keyframe, or storyboard work without changing story or asset responsibilities.
---

# Short-drama Prompt Compiler

Use this skill only after the script review and scene-continuity record are PASS and an asset decision exists. Read the D-drive core protocol first; it remains authoritative. Consume structured ProductionUnit and AssetDecision records, not an unreviewed prose summary.

## Default route

Use `direct_prompt` for ordinary prompt-first units. Require `keyframe_assisted` only when a critical composition or object state needs locking. Require `storyboard_required` for physical contact, multi-character choreography, complex handoffs, cross-space continuity, or a complex VFX path.

## Required prompt fields

Emit a provider-neutral `PromptUnit` object before writing provider syntax. Provide exactly one primary subject, primary action, action boundary, camera instruction and purpose, shot-language tuple, speaker and exact dialogue, start state, end state, reference responsibilities with scope, audio intent, continuity dependency, and task-specific prohibitions. Record the Skill ID/version/hash and an independent QA evidence path. Do not use a storyboard as an identity reference.

## Review skills

- Run the repository `short-drama-script-reviewer` Skill first; it reviews script structure against the D-drive `09_脚本优化与分镜拆解规范.md` (hook, beat chain, visible change points, and one visual cause per unit).
- Camera language should vary in scale, angle, movement, and purpose. Run `python -m production_control.shot_language_linter <ordered-units.json>`; intentional consecutive reuse requires a written `repeat_reason`.
- Provider/model-specific syntax is a later adapter concern. Use an installed provider skill only after the neutral prompt has passed this Skill and independent QA; the provider skill cannot rewrite the contract.

## Provider boundary

Compile a provider-neutral unit first. A provider adapter for RunningHub, 小云雀, or LibTV may translate syntax and parameter names only. It may not alter confirmed plot, duration, assets, action, dialogue, start/end states, or prohibitions. Adapter output must retain a source PromptUnit ID and provenance hash.

## Validation

Run `python -m production_control.prompt_linter <prompt-unit.json>` and `python -m production_control.contract_validator <production-contract.json>` before any adapter work. Passing validation does not authorize a paid submission.
