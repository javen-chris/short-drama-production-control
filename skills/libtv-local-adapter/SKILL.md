---
name: libtv-local-adapter
description: Compile a PASS provider-neutral short-drama PromptUnit into a local LibTV task over two independent channels (LIBTV_MCP / LIBTV_CLI), with mandatory auth preflight, eight-step node flow, idempotency and post-submission recording. Covers G6 submission only.
---

# LibTV local adapter (G6)

Full rules: `20_G6生成提交与平台调用规则_v3.0.md`. This skill is the executable
form of it. G6 is the only irreversible step in the pipeline — it spends money.

## Two channels, checked separately

`LIBTV_MCP` (Remote MCP) and `LIBTV_CLI` (official CLI) do **not** share auth state.
**A CLI token failure is not an MCP block.**

```
1. preflight MCP   → usable? use it; else record failure + error code, go to 2
2. preflight CLI   → usable? use it; log "MCP unavailable, degraded to CLI"; else go to 3
3. both unusable   → BLOCKED_LIBTV_AUTH: persist diagnostics, raise exception, stop
```

Never declare a total block from one channel's failure without preflighting the other.
Never substitute manual web-UI operation for either channel.

## Eight steps, in order — stop at the first failure

1. `AUTH_PREFLIGHT` — both channels, separately.
2. Asset upload — **prove the channel with one non-production test image first**, then batch.
3. Read back upload nodes — take the real node IDs, never assume them.
4. Collect asset → node ID mapping.
5. Create video node — `mixed2video` **requires** 1–15 real media nodes.
6. Wire reference images to the video node.
7. Read back the video node — confirm the wiring actually took effect.
8. Pre-generation preflight (assets, parameters, cost, authorization).

**Never continue to step 5 after step 2 failed.** That is how a node ends up built
with nothing bound to it. A local file path is not a platform media node.

## Authorization mode

Write `submission_mode` explicitly: `AUTONOMOUS_SUBMIT` or `HUMAN_FINAL_CLICK`.
Instruction authorized only up to QA ⇒ `HUMAN_FINAL_CLICK`, and then the agent
**must not submit or click the platform's generate button on the user's behalf**.
"Full auto / goal mode" is not submission authorization.

## Idempotency, timeout, retry

- Key = `f(unit_id, contract_id, provider, payload)`. On a hit: refuse, and report
  the existing `task_id` and its status. Never charge twice.
- On timeout: **query the original task first**. Blind re-submission is forbidden.
- After any submission, record immediately: real `task_id`, actual cost, output path,
  submitted-at, platform route.

## Error codes → stop rules

| code | action |
|---|---|
| `1100000102` (illegal request / invalid token) | stop the batch, preflight the other channel, do not continue uploading |
| `NODE_VALIDATION_FAILED` (missing media nodes) | stop node creation, back to step 3, one retry, then exception queue |
| `BLOCKED_LIBTV_AUTH` | stop, persist diagnostics, exception queue, wait for the user to fix the token |

Stop first, then diagnose **read-only** (`libtv account` / `libtv project list` / MCP status),
persist code + raw message + step + affected assets, then raise an exception whose
`only_decision` is one question the user can answer. Never make the user re-explain LibTV.

## Always

Credentials stay in the local connection — never into Git, task artifacts, prompts,
screenshots, logs, or QA evidence. Persist sanitized payload/hash, task ID, cost/status
and local output path. "Interface returned success" is not "asset bound and verified" —
step 7 read-back is the only proof. A provider success state is not QA PASS; send
real output to post-generation QA.
