---
name: short-drama-image-generator
description: Generate or edit short-drama image assets only through GPT-Image-2 — local subscription channel first, RunningHub workflow as an authorized paid fallback — and record channel provenance for every asset.
version: 0.1.0
---

# Short-drama image generator

Use this skill whenever an image asset must be produced or repaired: character,
face, wardrobe, scene, or prop MASTER; keyframes; storyboard composites. It is
the only sanctioned route to pixels. Read `14_RH生图渠道与GPT通道现状.md` for
RunningHub endpoint details and `16_生图渠道规则.md` for the rules.

## Model is pinned

`gpt-image-2` is the only allowed image model, for every asset class — there is
no "scenes may use something faster" exception. User ruling 2026-09-20 retires
`seedream-v5-pro`, `seedream-v4.5`, banana-family and `qwen-image` entirely,
including scene generation; they survive only as history in
`14_RH生图渠道与GPT通道现状.md` and must not be called. Any other model change
is never an agent decision; it needs explicit user authorization recorded as an
exception.

## Channel A — local subscription (default)

Consumes the ChatGPT subscription quota, costs no cash. Run the local wrapper:

```powershell
python D:\AIGC-Drama-Studio\tools\image_use_web.py "<prompt>" -o <out.png> -i <ref1.jpg> -i <ref2.jpg>
```

- downscale references first (long edge 1600, JPEG 200–550KB); large PNG uploads stall
- keep the conversation in the GPT account so the run can be reviewed later
- serial only: queue batches, do not fire them in parallel

## Channel B — RunningHub GPT-Image-2 workflow (fallback)

Only when the subscription quota is genuinely exhausted: `usage_limit_reached`,
HTTP 429, or a quota response carrying `resets_in_seconds` / `resets_at`. Being
slow or wanting steadier output is not a reason to switch.

Before calling it:

- explicit user authorization is required; without it the status is `BLOCKED_UNAUTHORIZED`
- webappId `2100124476636753922`, endpoint `/task/openapi/ai-app/run`, `Authorization: Bearer`
- nodeId 3 (plus 2 and 6) are references, nodeId 4 carries prompt / resolution / aspectRatio
- record the task id and the per-image cost; do not retry while `resets_in_seconds` is known

## Every image needs a provenance record

Emit an `image_channel` record per asset: asset role, image channel, model,
fallback reason, task id or conversation evidence, cost, and reference count
with each reference's duty (图1=人物 / 图2=场景 / 图3=道具). Validate with
`image_channel.schema.json`. An asset without this record does not enter the
asset registry.

## Never

- Never write a RunningHub API key into Git, contracts, task state, logs, or CI.
- Never let CI execute either channel; generation runs locally in an authorized session.
- Never treat a reference image as identity authority; identity stays with the approved MASTER.
- Never retry channel A endlessly after the quota is known to be exhausted.
