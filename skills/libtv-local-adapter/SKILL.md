---
name: libtv-local-adapter
description: Compile a PASS provider-neutral short-drama PromptUnit into a local LibTV task without letting canvas or provider behavior change approved story, assets, duration, or authorization.
---

# LibTV local adapter

Require PASS pre-generation QA, matching capability record and contract. Read only the user-selected LibTV canvas/project resources needed for the task. Translate syntax and bind assets by approved role; do not treat canvas conversation, unapproved media, or provider suggestions as production authority.

Credentials remain inside the local LibTV connection and never enter Git, task artifacts, prompts, screenshots, logs, or QA evidence. Persist sanitized payload/hash, task ID, cost/status and local output path.

Do not retry, switch provider/model, add assets, increase duration/cost, publish, or overwrite authority files without explicit permission. Send actual output to post-generation QA; a provider success state is not QA PASS.
