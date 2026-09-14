# Protocol mapping

Authoritative production rules remain in `D:\短剧制作核心协议`. This repository implements offline checks only.

| D-drive rule | First-release implementation |
|---|---|
| Gate and explicit production authorization | `production_contract.schema.json` and `contract_validator.py` |
| No retry, model switching, publishing, or MASTER overwrite without explicit authorization | immutable `false` authorization fields in the first-release schema |
| Prompt-first; storyboards only for complex risk | `storyboard_mode` plus risk-flag routing |
| Storyboard submitted to a video model must be a stitched composite | only `storyboard_composite` is an accepted storyboard role |
| Character/scene/prop/tail-frame responsibilities remain distinct | explicit asset roles and policy checks |
| Three generation channels | provider enum: `runninghub`, `xiaoyunque`, `libtv` |
| Independent QA after generation | planned next phase; no provider submission exists in this release |

## Boundary

Passing validation does not mean a video has been generated and does not grant paid submission. It only means that an adapter may be considered after the relevant authority document and user authorization have been checked.

