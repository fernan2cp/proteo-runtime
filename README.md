# Proteo Runtime

Provider-neutral runtime contracts for asynchronous model execution. Version
0.1.0 establishes the repository and architectural foundation described in the
Phase 0 SDD.

## Status

Phase 0 is implemented locally. Provider integrations, LangGraph adapters,
tool execution, observers, authentication, and security enforcement are
deliberately deferred.

## Install

```text
uv add proteo-runtime
```

For contributors, install the development environment with `uv sync --extra dev`.

## Minimal usage

```python
from proteo_runtime import RuntimeInput
from proteo_runtime.testing import FakeRuntime, FakeTurn

runtime = FakeRuntime(turns=[FakeTurn(value="hello")])
```

The fake runtime is deterministic and never starts Codex, reads credentials,
opens a network connection, or consumes provider quota.

## Development

Run formatting, linting, typing, import-boundary checks, and tests with:

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest --cov=proteo_runtime --cov-report=term-missing
```

See `docs/plans/active/phase-0-repository-architectural-foundation/` for the
requirements, design, acceptance criteria, and validation evidence.
