# Short Drama Production Control

This private repository is the code control plane for the D-drive short-drama protocol. It is deliberately **not** the authority for scripts, MASTER assets, media, or API keys.

## First release

- validates `production_contract.json` before any provider adapter can submit work;
- lints a prompt production unit before routing;
- treats prompts as the default path and storyboards as a risk-triggered exception;
- has no network calls, provider calls, retry loop, or paid-task submission.

## Providers

The same contract supports only these provider adapters:

- `runninghub`
- `xiaoyunque`
- `libtv`

Adapters are intentionally not implemented in the first release. A future adapter may translate validated inputs into provider parameters, but must not change story, asset responsibilities, duration, or prohibited actions.

## Local use

```powershell
python -m pip install -e ".[dev]"
python -m production_control.contract_validator examples/production_contract.valid.json
python -m production_control.prompt_linter examples/prompt_unit.direct.json
pytest
```

See [docs/protocol-mapping.md](docs/protocol-mapping.md) for the mapping to the D-drive authority documents.

