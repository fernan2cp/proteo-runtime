# Proteo Runtime

Provider-neutral runtime contracts for asynchronous model execution. Version
`0.3.1` hardens model resolution, structured output, context policies, Codex
session migration, and deterministic lifecycle behavior on top of the Phase 2 runtime.

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
for the historical Phase 2 record and
`docs/plans/active/phase-2.1-cross-phase-conformance-hardening/` for the current
conformance hardening tracker; Phase 0 and Phase 1 records remain historical.

Configuration bindings are validated against the complete Codex catalog at startup and frozen
when models or sessions are created. Structured output always sends its schema to the SDK and
validates locally; invalid output is retried at most twice by default and raw output is opt-in
and sanitized. Persistent sessions accept only user context under `runtime`, reject assistant/tool
replay under `hybrid`, and migrate on the same provider thread without replaying or deleting history.
