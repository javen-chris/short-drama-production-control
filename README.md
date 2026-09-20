# Multi-Agent Production Control

A source-controlled **control plane** for multi-agent production workflows. It decomposes a complex, multi-stage production process into routable agent roles, enforces quality gates before and after generation, and governs every artifact with provenance — so a pipeline runs repeatably, with reviewable evidence instead of ad-hoc coordination.

It is deliberately **not** the authority for scripts, MASTER assets, media, or API keys. It is the layer that decides *what may proceed, on what evidence, and in what order*.

> Validated end-to-end on a real high-complexity pipeline: **scripted episodic video production** — script breakdown → independent script review → scene continuity → adaptive asset routing → prompt compilation → generation → pre/post QA → version governance.

## Why this exists

Complex production processes fail in predictable ways:

- **state drifts between stages**, so later steps silently contradict earlier ones;
- **quality is checked only at the end**, when rework is most expensive;
- **reruns are not reproducible**, and no one can prove why an output was accepted;
- **prompts and assets are edited ad hoc**, with no version or provenance trail.

This control plane addresses each of those with explicit contracts, gates, and governance — not with a bigger prompt.

## Control plane

- validates `production_contract.json` before any provider adapter can submit work;
- lints a prompt production unit before routing;
- requires every video prompt to record Skill provenance, an independent QA `PASS`, and a `PASS` script review;
- checks consecutive shot-language reuse and requires a stated reason when repetition is intentional;
- implements a source-controlled Skill chain for routing, breakdown, independent script review, scene continuity, adaptive assets, conditional storyboards, neutral prompts, pre/post QA, and three local provider adapters;
- persists confirmed workflow decisions in `docs/decisions/` and adaptive asset routing in `docs/architecture/`;
- pins every image asset to one declared model and channel, with the paid fallback used only on a recorded reason and explicit authorization;
- keeps task state, asset decisions, provider capabilities, unified QA checks, provenance hashing, payload compilation, and PR security scanning;
- keeps a dated AIGC production benchmark and reuse boundary in `docs/research/`;
- treats prompts as the default path and storyboards as a risk-triggered exception;
- keeps validation offline; provider credentials and actual submissions stay local.

## Providers

The same contract supports only these provider adapters:

- `runninghub`
- `xiaoyunque`
- `libtv`

Each provider has a repository Skill describing its adapter boundary. These Skills do not contain credentials or network implementation. They may translate validated inputs into provider parameters, but cannot change story, asset responsibilities, duration, or prohibited actions. Actual submission requires local credentials and explicit contract authorization.

## Skill chain

The executable chain declaration is `skills/skill-chain.json`. Validate it with:

```powershell
python -m production_control.skill_chain_validator
```

Install or refresh the repository Skills in the current user's Codex Skill directory with:

```powershell
powershell -ExecutionPolicy Bypass -File tools/install_repo_skills.ps1
powershell -ExecutionPolicy Bypass -File tools/install_repo_skills.ps1 -Replace
```

`-Replace` deletes and recopies only the exact Skill folders named by the repository manifest. It never copies API keys. Restart Codex after installation so discovery is refreshed.

## Local use

```powershell
python -m pip install -e ".[dev]"
python -m production_control.contract_validator examples/production_contract.valid.json
python -m production_control.prompt_linter examples/prompt_unit.direct.json
pytest
```

See [docs/protocol-mapping.md](docs/protocol-mapping.md) for the mapping to the local authority protocol documents.

## Design notes

- **Contract-first.** Nothing reaches a provider adapter without a validated contract.
- **Gates over trust.** Generation is expensive; independent review runs before and after, and no stage repairs the objects it reviews.
- **Provenance by default.** Every accepted artifact traces back to its inputs and decisions.
- **Domain-portable.** The chain is defined by roles and gates, not by the content it produces. The same skeleton applies to any multi-stage pipeline with hard continuity constraints.
