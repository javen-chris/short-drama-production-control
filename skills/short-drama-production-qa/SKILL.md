---
name: short-drama-production-qa
description: Independently review short-drama artifacts before generation or actual rendered media after generation; PASS, FAIL, and UNCERTAIN determine whether the pipeline may advance.
---

# Production QA

Do not generate or silently repair the artifact being reviewed. Store evidence paths and findings separately. `FAIL` and `UNCERTAIN` block downstream work.

## pre_generation

Read the RUN contract's current QA level and applicable Gate protocol bundle. Use `capabilities/qa_policy.json` as the single source for A/B/C scope:

- **A:** inspect only changed files and the context needed to understand the edit; finish within 180 seconds. Do not expand to a full review for a harmless wording change.
- **B:** inspect the changed shot and its immediately adjacent shots, plus only the continuity evidence they depend on.
- **C:** inspect the current candidate's required script, breakdown, Prompt, asset contract/references, relevant start/end states, and project state as one consolidated pre-generation review.

Across levels, check authority/version, applicable protocol refs, evidence freshness, and only the content risks in scope. A schema pass is not content QA. Do not reload unrelated historical versions or the entire project when the contract identifies a narrower evidence bundle.

## post_generation

Inspect the actual local media, not the task-success flag. Verify decode, duration, resolution/frame rate/audio; identity, face/hair/wardrobe/body/footwear; character count; blocking and screen direction; prop ownership/state; required action result; dialogue speaker/lip-sync/audio; VFX source/path; continuity against the prior real tail; black/flash/frozen/corrupt frames; unwanted text/watermark; and compliance with prohibitions.

Write per-check `PASS`, `FAIL`, or `UNCERTAIN` with evidence. On `FAIL`, group findings before returning them so the producer can make one consolidated repair. Permit at most one same-issue re-review on the same version; if the artifact changes materially, record a new version and run the appropriate QA once. A timeout is not a failure verdict: stop at the time limit, narrow the evidence bundle, and use only the policy-defined re-review.

## Material changes and review limits

QA findings do not authorize a creative rewrite. Classify each proposed correction against `22_用户决策交互与版本防循环规则_v3.0.md`; material changes require a decision card and active-thread question before editing. Limit each version to one consolidated review and, after a bounded minor correction, one targeted re-review.

## Fixed final-packet QA
For RunningHub review only the compiled final submission packet and bound snapshots, never raw template defaults. Caller dispatches gpt-5.6-terra and records startup, session ID and completion as client evidence. Record reviewed_packet_sha256. Missing invocation evidence is an execution exception, not a content FAIL; do not invent cryptographic server identity requirements that the tool does not implement. See 23_RH最终提交包与资产快照规则_v1.md and tools/final_packet.py.
