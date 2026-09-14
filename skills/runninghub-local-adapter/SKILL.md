---
name: runninghub-local-adapter
description: Compile a PASS provider-neutral short-drama PromptUnit into a RunningHub payload and, only when explicitly authorized, submit or query one task locally with secrets kept outside GitHub.
---

# RunningHub local adapter

Require a PASS pre-generation QA, matching production contract, capability record, approved workflow ID, and source PromptUnit provenance. Translate parameter names only; do not change story, duration, assets, dialogue, states, or prohibitions.

Read `RUNNINGHUB_API_KEY` only from the local process environment. Never place it in Git, `.env` committed files, contracts, payload archives, task state, prompts, logs, screenshots, or QA evidence. Redact authorization headers and secret-like response fields.

Before submitting, query or reconcile any existing task ID. Submit at most the explicitly authorized attempt, record sanitized payload hash, task ID, cost and response path, then stop. Unknown state, failure, retry, model/workflow change, added duration, or added cost requires new authority. GitHub Actions must not execute this Skill or receive the key.
