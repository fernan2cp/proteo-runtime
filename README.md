# Proteo Runtime

Provider-neutral runtime contracts for asynchronous model execution. Version
`0.3.0` adds model resolution, structured output, context policies, and Codex
session migration on top of the Phase 1 runtime.

## Status

Phase 0 contracts remain provider-neutral. Phase 1 adds a Codex provider behind
`proteo_runtime.providers.codex.CodexRuntime`. Phase 2 adds explicit JSON
configuration, immutable profile resolution, host-validated structured output,
and same-thread session migration. Host-managed tools, native tools, strong OS
isolation, general retries, and LangGraph remain deferred.

## Install

```text
uv add proteo-runtime
```

For contributors, install the development environment with `uv sync --extra dev`.

## Minimal usage

```python
from proteo_runtime.providers.codex import CodexRuntime

async with CodexRuntime() as runtime:
    model = await runtime.brain()
    result = await model.ainvoke("Hello")
```

The Codex provider uses the pinned `openai-codex>=0.147,<0.148` SDK and a
ChatGPT-managed Codex login. The core package never imports the SDK. Default
unit and contract tests use SDK doubles and never read credentials, access the
network, or consume quota. JSON Schema support is provided by the base
dependency `jsonschema>=4,<5`; pass `config_path=` or set
`PROTEO_RUNTIME_CONFIG` to select an explicit UTF-8 configuration file.

## Development

```text
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run lint-imports
uv run pytest -q
uv build
```

Real Codex integration tests are opt-in only:

```text
PROTEO_CODEX_INTEGRATION=1 uv run pytest -m integration tests/integration/codex -q
```

See `docs/plans/complete/phase-2-model-resolution-structured-output-context/`
for the completed Phase 2 requirements, design, acceptance criteria,
validation evidence, rollout, and traceability; the Phase 1 record remains in
`docs/plans/complete/phase-1-codex-core-runtime/`.
