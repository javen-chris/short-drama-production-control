# Short Drama Production Control

This private repository is the code control plane for the D-drive short-drama protocol. It is deliberately **not** the authority for scripts, MASTER assets, media, or API keys.

## Control plane

- validates `production_contract.json` before any provider adapter can submit work;
- lints a prompt production unit before routing;
- requires every video prompt to record Skill provenance, independent QA `PASS`, and a `PASS` script review;
- checks consecutive shot-language reuse and requires a reason when repetition is intentional;
- implements a source-controlled Skill chain for routing, breakdown, independent script review, scene continuity, adaptive assets, conditional storyboards, neutral prompts, pre/post QA, and three local provider adapters;
- persists confirmed workflow decisions in `docs/decisions/` and adaptive asset routing in `docs/architecture/`;
- provides task state, asset decisions, provider capabilities, unified QA checks, provenance hashing, payload compilation, and PR security scanning;
- keeps a dated GitHub AIGC workflow benchmark and reuse boundary in `docs/research/`;
- treats prompts as the default path and storyboards as a risk-triggered exception;
- keeps GitHub validation offline; provider credentials and actual submissions stay local.

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

See [docs/protocol-mapping.md](docs/protocol-mapping.md) for the mapping to the D-drive authority documents.
