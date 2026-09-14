# Protocol mapping

Authoritative production rules remain in `D:\短剧制作核心协议`. This repository implements offline checks only.

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

The complete order is machine-checked from `skills/skill-chain.json`; CI must fail when a declared Skill is missing or a dependency appears after its consumer.

## Boundary

Passing validation does not mean a video has been generated and does not grant paid submission. It only means that an adapter may be considered after the relevant authority document and user authorization have been checked.
