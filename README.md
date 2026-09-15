# Proteo Runtime

Provider-neutral runtime contracts for asynchronous model execution. Version
`0.2.0` adds the opt-in Codex Core Runtime described by the active Phase 1 SDD.

## Status

Phase 0 contracts remain provider-neutral. Phase 1 adds a Codex provider behind
`proteo_runtime.providers.codex.CodexRuntime`; real subscription-backed tests pass opt-in; remote CI and strong OS isolation remain explicitly pending.

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
network, or consume quota.

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

Structured output, session migration, host-managed tools, retries, and strong
OS isolation are reserved for later phases. See
`docs/plans/active/phase-1-codex-core-runtime/` for requirements, design,
acceptance criteria, validation evidence, and traceability.
