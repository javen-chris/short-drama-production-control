# Protocol mapping

> **对应协议版本：3.0**（2026-09-20 定版）。协议升版时本文件需同步复核；协议文件名的 `_v3.0` 后缀变更必须同时更新 `protocol_fingerprint.REQUIRED_CORE_FILES` 与 `run_compliance.STEP_PROTOCOL_REQUIREMENTS`。

Authoritative production rules remain in `D:\AIGC短剧本地工作流规则及协议\短剧制作核心协议`. This repository implements offline checks only.

| D-drive rule | First-release implementation |
|---|---|
| Gate and explicit production authorization | `production_contract.schema.json` and `contract_validator.py` |
| No retry, model switching, publishing, or MASTER overwrite without explicit authorization | immutable `false` authorization fields in the first-release schema |
| Prompt-first; storyboards only for complex risk | `storyboard_mode` plus risk-flag routing |
| Every video prompt must be Skill-produced and QA-approved | `skill_production`, `qa_review.status=PASS`, and `script_review.status=PASS` |
| Avoid meaningless repeated camera language | `shot_language_linter.py`; repeats require `repeat_reason` |
| Task/Gate routing and persistent continuation | `short-drama-production-router` |
| Script-to-shot-to-production-unit decomposition | `short-drama-script-breakdown` |
| Script rhythm and shot decomposition review | repository Skill `short-drama-script-reviewer` and `script_review.status=PASS` |
| Scene, blocking, axis, prop and tail-frame continuity | `short-drama-scene-continuity` |
| Adaptive asset readiness and risk routing | `docs/architecture/adaptive-asset-routing.md` and the decision record in `docs/decisions/` |
| Minimum necessary asset route | `short-drama-asset-router` |
| Storyboard submitted to a video model must be a stitched composite | only `storyboard_composite` is an accepted storyboard role |
| L1 key states and L2 storyboard plan | `short-drama-storyboard-planner` |
| Character/scene/prop/tail-frame responsibilities remain distinct | explicit asset roles and policy checks |
| Three generation channels | provider enum: `runninghub`, `xiaoyunque`, `libtv` |
| Independent QA before and after generation | `short-drama-production-qa` in `pre_generation` and `post_generation` modes |
| Local-only provider translation/submission boundary | `runninghub-local-adapter`, `xiaoyunque-local-adapter`, `libtv-local-adapter` |
| One allowed image model with two channels: local subscription first, RunningHub workflow as authorized paid fallback | `image_channel.py`, `image_channel.schema.json`, and `IMAGE_CAPABILITIES` in `capabilities.py` |
| Tail frames and storyboards are authorization-gated; missing ones degrade instead of blocking | `authorization.allow_tail_frame_generation` / `allow_storyboard_generation`, `DEGRADED_DIRECT` route, `fallback_notes` |
| Asset identity pinned to a file and hash, never a free-form path | `asset_registry.schema.json` and `asset_registry.py` |
| Pre-node hard gate with a mandatory MASTER manifest | `preflight.schema.json` and `preflight_gate.py` |
| Stable layer separate from the shot layer | `series_contract.schema.json` |
| Production units split for a stated reason only | `production_unit.split_rationale` and `split_argument` |
| Face-only references never stand in for wardrobe or body | `face_identity_master` / `wardrobe_body_master` roles and `identity_scope_errors` |
| Eight QA classes and rework accounting | `qa_report.py`: `classify_rework`, `top_rework_classes` |
| No duplicate paid submission; observed cost | `cost_ledger.py` idempotency keys and `cost_ledger.schema.json` |
| Exception queue and edit candidate pool | `exception_queue.schema.json`, `edit_candidate.schema.json` |
| Pipeline can pause, wait for approval, and resume from a checkpoint | `orchestrator.py`, `run_state.py`, `run_state.schema.json` |
| A run can be read step by step without digging through logs | `run_report.py`: text summary or self-contained HTML (`python -m production_control.run_report <run_state.json> --html report.html`) |
| A 20-segment episode stays navigable and its progress is viewable live | `run_index.py` (one file per segment + one index per episode), `run_server.py` (`--serve` for a refreshable live page), `run_index.schema.json` |
| Video submissions carry complete content, not just authorization | `submission_report.py` (`python -m production_control.submission_report <report.json> [--project-root DIR]`), `submission_report.schema.json` |
| Provider limits declared, not guessed | `capabilities/providers.json` with `provider_capability.schema.json` |
| Agents must prove they read the current core protocol before producing | `tools/protocol_fingerprint.py`, `protocol_attestation.py`, `protocol_attestation.schema.json` |
| Image assets exist only via GPT-Image-2, subscription channel first; seedream, banana, and qwen-image retired by user ruling 2026-09-20 | `short-drama-image-generator` Skill, `image_channel.py`, `image_channel.schema.json` |
| Image generation itself requires prior user confirmation | `requires_user_confirmation` gate on the local `gpt-image-use-channel` Skill |

The complete order is machine-checked from `skills/skill-chain.json`; CI must fail when a declared Skill is missing or a dependency appears after its consumer.

## Boundary

Passing validation does not mean a video has been generated and does not grant paid submission. It only means that an adapter may be considered after the relevant authority document and user authorization have been checked.
