---
name: short-drama-production-router
description: Route an authorized D-drive short-drama task through the current Gate and the minimum required production Skills without granting generation, retry, spending, publishing, or overwrite permission.
---

# Short-drama production router

Read `<PROTOCOL_ROOT>\00_自动化生产唯一入口.md`, `AGENTS.md`, the core package, current project entry, `TASK_CURRENT.md`, contract, confirmed script, and asset index. Run Bootstrap when the task card does not yet exist.

Identify the current Gate and invoke only its Skill. Persist every input path, output path, status, evidence, exception, task ID, cost, and next step. Never rely on chat memory as production state.

Route in this order: breakdown → script review → scene continuity → asset decision → conditional storyboard/key states → neutral prompt → pre-generation QA → one selected provider adapter → post-generation QA.

Stop on missing/conflicting authority, missing MASTER or required real tail frame, `FAIL`, `UNCERTAIN`, unknown provider task state, or an action outside the contract. A missing derived document is not a blocker; create it within the current Gate. Passing a Gate never expands authorization.

## User decision handoff and anti-loop

Read `22_用户决策交互与版本防循环规则_v3.0.md` before routing a blocker. Never treat an internal `current_owner=user` state as a user-facing handoff. For a material change, create the decision card and ask the exact question in the active user conversation. Until answered, keep the same RUN/version and do not re-review or proceed through dependent steps.
