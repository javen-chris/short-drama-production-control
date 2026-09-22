---
name: short-drama-image-generator
description: Generate or edit short-drama image assets only through GPT-Image-2 in the Hermes or Codex foreground — local subscription channel first, RunningHub workflow as an authorized paid fallback — and record channel provenance for every asset.
version: 0.2.0
---

# Short-drama image generator

Use this skill whenever an image asset must be produced or repaired: character,
face, wardrobe, scene, or prop MASTER; keyframes; storyboard composites. It is
the only sanctioned route to pixels. Read `14_RH生图渠道与GPT通道现状.md` for
RunningHub endpoint details and `16_生图渠道规则.md` for the rules.

## The provenance record is metadata, not a second copy

Do not misread the ledger requirement: `image_channel` is **one metadata entry
per generated image**, not a copy of the image.

- The image is written **once**, into the project's own asset folder, following
  the project's declared layout (`场景资产/`, `物品资产/`, `故事本&首尾帧/`, or the
  series library `人物资产库/`). This skill never hard-codes an absolute path and
  never asks for a special asset folder.
- Never duplicate an image "for the record". The ledger references it by
  relative path and stores no image bytes.
- Use **one append-only ledger per project**, `workflow/image_channel_log.json`
  by default, or wherever the project's entry file declares. Not one file per
  image. Validate it with `image_channel_log.schema.json` and
  `validate_ledger()`, which also rejects duplicate references and paths that do
  not exist.

## Who authorizes the generation

This depends on the production mode, per the user ruling of 2026-09-20:

- **Autonomous target mode** (the user asked for "全自动 / 目标模式"): that start
  command is itself the one-time authorization for filling missing assets. When
  asset assessment finds a missing MASTER, keyframe, or storyboard, **generate
  immediately, run independent QA, and continue on PASS** - do not stop and ask
  per image. The paid RunningHub fallback is covered by the same authorization
  once the subscription quota is exhausted.
- **Regular gated flow** (the user confirms step by step): report the missing
  asset at G3/G4 and wait for explicit authorization.

Either way, four things are not optional: QA PASS before an asset is used as a
MASTER, an `image_channel` record per generation, a recorded cost, and never
overwriting an already-confirmed MASTER (new versions are generated as
candidates and only replace it after QA and user confirmation). Pause when QA
fails twice in a row or cumulative cost exceeds `budget_cny`.

## Model is pinned, and production happens in the foreground

**`gpt-image-2` is the only allowed image model**, for every asset class — there
is no "scenes may use something faster" exception. User ruling 2026-09-20 retires
`seedream-v5-pro`, `seedream-v4.5`, banana-family and `qwen-image` entirely,
including scene generation; they survive only as history in
`14_RH生图渠道与GPT通道现状.md` and must not be called. Any other model change
is never an agent decision; it needs explicit user authorization recorded as an
exception.

**All image generation and editing runs in the Hermes or Codex foreground on
this machine.** The agent invoking this skill drives the generation itself, live
in the session — it is never delegated to a background job, a scheduled task, or
a headless worker, and CI must never execute either channel. This is a standing
requirement of the user, not a default that can be optimized away.

## Channel A — local subscription (default)

Consumes the ChatGPT subscription quota, costs no cash. Run the local wrapper:

```powershell
python D:\AIGC-Drama-Studio\tools\image_use_web.py "<prompt>" -o <out.png> -i <ref1.jpg> -i <ref2.jpg>
```

Operational details that matter (each one was a historical failure point):

- **Downscale references first** — long edge 1600, JPEG 200–550KB. Large
  PNG uploads (7MB-class) stall at the upload step and hang the whole run; this
  was the root cause of the early multi-reference failures.
- **Keep the conversation in the GPT account** (`--keep-conversation`) so the
  run can be reviewed later from inside the account.
- **Do not pile up Chrome tabs** — do not pass `--keep-tab`; the tab closes by
  itself when the run ends.
- **Serial only** — the web backend is 1-concurrent, roughly 40–90 s per image.
  Queue batches; never fire them in parallel against the same account
  (>10 images/min trips the rate limit).
- **Trim multi-reference prompts** — with several characters in one frame,
  designate a single main reference per frame and write the others as
  back-of-head or off-frame hands, otherwise faces contaminate each other.
- Healthy log sequence:
  `attaching N reference(s) → waiting for reference uploads: n/N ready → all N uploaded → prompt submitted once → generating → ✓ saved`.
- A `could not delete conversation` warning is normal when keeping the
  conversation — not an error.
- Quota exhaustion is a channel signal, not a config error: HTTP 429 with
  `usage_limit_reached`, `plan_type`, `resets_at` / `resets_in_seconds` means the
  chain is healthy and only the quota is gone. Convert `resets_at` to local time
  instead of guessing.

PowerShell pitfall: write `--project=` (equals form), never `--project ""` —
PowerShell swallows the empty string and argparse exits with code 2. Omitting the
flag entirely sends the run to the ChatGPT "Work" tab and consumes the wrong
quota pool.

If the wrapper is unavailable, the underlying CLI lives at
`~/.local/share/image-use/image-use` with `~/.local/bin/chrome-use.exe` on PATH.
Keep `IMAGE_USE_NO_AUTO_UPDATE=1` set, otherwise an auto-update overwrites the
local pipe patch that makes the tool usable here.

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

- Never use a model other than `gpt-image-2`.
- Never run generation outside the Hermes/Codex foreground session.
- Never write a RunningHub API key into Git, contracts, task state, logs, or CI.
- Never let CI execute either channel; generation runs locally in an authorized session.
- Never treat a reference image as identity authority; identity stays with the approved MASTER.
- Never retry channel A endlessly after the quota is known to be exhausted.
