# Validation plan

## Focused and semantic tests

Run focused tests after each workstream, including terminal exclusivity, EOF without terminal,
abandoned stream interruption, close waiting, busy resume, descriptor tampering, descriptor-only
migration, workspace cleanup, twelve mapping catalog validation, schema immutability, retry/raw
precedence and fake/provider event parity.

## Local gates

```text
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pre-commit run --all-files
uv run pytest tests -q --cov=proteo_runtime --cov-branch --cov-report=term-missing --cov-fail-under=90
uv build
uv run python scripts/check_artifacts.py dist
```

Install both wheel and sdist in isolated Python 3.11 environments and assert import, CLI version
and module version `0.3.1`.

## Opt-in integration and CI

With `PROTEO_CODEX_INTEGRATION=1`, run the catalog check and representative text, structured,
session and migration smokes. Tests may delete only disposable resources they create. Push the
branch, wait for the complete Linux/Windows Python 3.11–3.14 matrix, and record run URLs.

