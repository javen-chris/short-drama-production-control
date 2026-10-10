# Protocol mapping

> This repository implements offline production controls. The authority root is configured locally or by `SHORT_DRAMA_PROTOCOL_ROOT`; the sanitized release copy is `protocol_release/3.6/短剧制作核心协议`.

## Current workflow

New work uses G0-S01 for project intake and RUN recovery, then the applicable production steps through G6-S12. G6-S12 queries the already-submitted provider task. A verified terminal result and output link end the RUN. Download and post-generation review are separate user-requested work.

| Concern | Implementation |
|---|---|
| Stable displayed step IDs and legacy mapping | `skills/skill-chain.json`, `src/production_control/step_registry.py` |
| Goal-scoped contract and selected provider | `production_contract.schema.json`, `execution_contract.py` |
| Gate status and independent pre-generation QA | `capabilities/qa_policy.json`, `qa_policy.py`, `step_audit.py` |
| Hash-aware event evidence and RUN recovery | `progress.py`, `resume_run.py`, `tools/resume_run.py` |
| Asset identity, confirmation and change history | `asset_registry.schema.json`, `asset_registry.py`, `tools/validate_asset_index.py` |
| Submission intent, idempotency and provider Task ID | `final_submission.py`, `authorize_video_submission.py`, `record_provider_event.py` |
| Scoped protocol changes and read attestations | `protocol_versions.py`, `protocol_fingerprint.py`, `migrate_run_protocol.py` |

Core rules are loaded deterministically. Non-core history uses keyword and metadata search by project, stage, asset ID, version and current status. This release does not require a vector database or full RAG.

The implementation and search metadata policy are described in [任务知识库实施策略.md](任务知识库实施策略.md).
