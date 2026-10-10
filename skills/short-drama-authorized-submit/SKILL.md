---
name: short-drama-authorized-submit
description: Submit one preflighted short-drama video task to the already selected provider, only under explicit per-submission authorization, and record the actual task ID.
---

# Authorized submission

Run only after G5-S09 passed, the submission report is complete, the provider is fixed in the contract, and explicit authorization for this exact submission is recorded.

Before submission, verify the contract, target project/session, prompt and model parameters, referenced assets and hashes, billing route, remaining budget, idempotency key, and prior provider task IDs. If a matching submission already exists, do not submit again; route to G6-S12 to query its recorded task ID.

Submit at most once within the recorded authorization. Do not retry, switch provider/model, increase budget, or expand scope. Persist the provider response and actual task ID as execution facts. A request accepted by the provider means submitted, not completed or content-approved.

If authorization, report, billing route, asset binding, or provider identity cannot be verified, stop and record the specific blocker.
