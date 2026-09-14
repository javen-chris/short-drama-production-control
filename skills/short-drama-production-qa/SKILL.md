---
name: short-drama-production-qa
description: Independently review short-drama artifacts before generation or actual rendered media after generation; PASS, FAIL, and UNCERTAIN determine whether the pipeline may advance.
---

# Production QA

Do not generate or silently repair the artifact being reviewed. Store evidence paths and findings separately. `FAIL` and `UNCERTAIN` block downstream work.

## pre_generation

Verify authority/version, time coverage, beat and script review, shot-to-unit mapping, continuity ledger, asset roles, risk route, storyboard composite when required, neutral PromptUnit, provider capability, Skill ID/version/hash, contract authorization, expected cost, and absence of secrets. Schema success alone is not content QA.

## post_generation

Inspect the actual local media, not the task-success flag. Verify decode, duration, resolution/frame rate/audio; identity, face/hair/wardrobe/body/footwear; character count; blocking and screen direction; prop ownership/state; required action result; dialogue speaker/lip-sync/audio; VFX source/path; continuity against the prior real tail; black/flash/frozen/corrupt frames; unwanted text/watermark; and compliance with prohibitions.

Write `PASS`, `FAIL`, or `UNCERTAIN`, per-check evidence, media path/hash, provider task ID, cost, reviewer identity, and the only permitted next step. Post-generation failure does not authorize retry or provider switching.
