# Adaptive asset routing

## Asset decision record

Each production unit should produce an `ASSET_DECISION` record before provider routing:

```json
{
  "unit_id": "EP01-U03",
  "prompt_only": "FAIL",
  "risk_factors": ["multi_character_choreography", "complex_prop_handoff"],
  "missing_assets": [
    {"role": "prop_master", "purpose": "lock prop shape, material, and ownership", "minimum_scope": "single prop turnaround"}
  ],
  "recommended_route": "keyframe_assisted",
  "reason": "Prompt alone cannot reliably constrain the handoff and contact state",
  "estimated_extra_work": "one prop MASTER and one key state image",
  "blocked_until": ["prop_master", "keyframe_qa_pass"]
}
```

## Route guidance

### `PROMPT_ONLY_READY`

Use for ordinary single/two-person performance, one space, one visual cause, no complex contact, and available character/scene references.

### `KEYFRAME_REQUIRED`

Use when composition, screen direction, a prop position, or start/end pose must be locked but a full storyboard is unnecessary.

### `ASSET_PLAN_REQUIRED`

Use when an authoritative character, clothing, scene, or prop reference is missing. Propose the smallest reference asset and stop provider routing until its independent QA passes.

### `STORYBOARD_REQUIRED`

Use for multi-person choreography, physical contact, complex handoff, cross-space continuity, or complex VFX paths. The video model receives the ordered stitched composite, never the individual storyboard cells one by one.

## Non-negotiable checks

- A face-only reference cannot silently become a full-body clothing reference.
- A storyboard cannot replace a character or scene MASTER.
- A concept image or QA contact sheet cannot replace a real tail frame.
- Missing assets are reported, not invented.

