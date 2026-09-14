---
name: short-drama-asset-router
description: Decide whether an approved production unit is safe for prompt-only, key-state, missing-asset, or storyboard production and request only the minimum authoritative assets needed.
---

# Adaptive asset router

Consume a PASS script review, PASS continuity ledger, production unit, and current asset index. Run the deterministic asset decision code, then explain the smallest sufficient route without generating assets.

- L0 / `PROMPT_ONLY_READY`: simple performance in one stable space with authoritative references and no complex contact or critical state ambiguity.
- L1 / `KEYFRAME_REQUIRED`: composition, position, start/end pose, screen direction, or one critical object state needs 2–4 key-state images.
- `ASSET_PLAN_REQUIRED` or `BLOCKED_MISSING_MASTER`: identity, wardrobe, scene, prop, or real-tail authority is missing/conflicting. Request the minimum missing MASTER and stop.
- L2 / `STORYBOARD_REQUIRED`: multi-person choreography, physical contact, fight, handoff, cross-space continuity, complex VFX path, or a critical reversal whose causal states cannot be constrained reliably by prompt alone.

Record risk evidence, missing roles, minimum scope, route, reason, extra work, and unblock conditions. Do not escalate every non-empty risk to a storyboard; do not let a storyboard substitute for character, scene, prop, wardrobe, or real-tail authority.
