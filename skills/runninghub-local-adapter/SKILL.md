---
name: runninghub-local-adapter
description: Compile a PASS provider-neutral short-drama PromptUnit into a RunningHub payload and, only when explicitly authorized, submit or query one task locally with secrets kept outside GitHub.
---

# RunningHub local adapter

Require a PASS pre-generation QA, matching production contract, capability record, approved workflow ID, and source PromptUnit provenance. Translate parameter names only; do not change story, duration, assets, dialogue, states, or prohibitions.

Read `RUNNINGHUB_API_KEY` only from the local process environment. Never place it in Git, `.env` committed files, contracts, payload archives, task state, prompts, logs, screenshots, or QA evidence. Redact authorization headers and secret-like response fields.

Before submitting, query or reconcile any existing task ID. Submit at most the explicitly authorized attempt, record sanitized payload hash, task ID, cost and response path, then stop. Unknown state, failure, retry, model/workflow change, added duration, or added cost requires new authority. GitHub Actions must not execute this Skill or receive the key.

## Final submission packet (2026-10-10 user rule)
Compile the complete provider request BEFORE QA, including prompt, duration, aspect, image upload bindings, snapshot hashes and disabled audio inputs. QA receives only this compiled packet and its snapshots, never raw workflow defaults. QA model is gpt-5.6-terra. Require PASS with reviewed_packet_sha256 matching the canonical packet digest. Recheck snapshot hashes and send the identical payload; never rebuild nodes or replace uploads after QA. Missing or changed hash invalidates the prior QA. Use production_control.final_submission for this gate. Read `$SHORT_DRAMA_PROTOCOL_ROOT/23_RH最终提交包与资产快照规则_v1.md`.

Asset-upload preparation may precede S09 only within the already authorized task asset scope; upload authority does not grant video submission authority. Use tools/final_packet.py bind/qa/check and record --qa-invocation-evidence in qa_verdict.py. The provider transport calls submit_bound_packet to send the reviewed payload verbatim; unknown submission consumes the reserved attempt and requires reconciliation, never retry.
