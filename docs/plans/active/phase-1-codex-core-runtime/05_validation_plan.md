# Validation Plan — Phase 1

## Default Quota-Safe Validation

Run from the repository root:

```text
uv sync --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest -q
uv run pytest --cov=proteo_runtime --cov-report=term-missing
uv build
uv run python scripts/check_artifacts.py
```

The default test configuration must skip real-runtime tests when
`PROTEO_CODEX_INTEGRATION` is absent or not `1`. `tests/contract/test_quota_safety.py` must patch
process, network, authentication, and SDK-construction boundaries so an accidental real call
fails the suite.

## Focused Test Areas

| Area | Planned evidence | Criteria |
|---|---|---|
| Provider boundary/lifecycle | SDK-factory doubles and import contracts | AC-P1-002–003 |
| Authentication/identity | account variants and secret/PII assertions | AC-P1-004–005 |
| Catalog/resolution | model fixtures, default cardinality, effort validation | AC-P1-006–007 |
| Brain/security | captured `thread_start`/turn arguments and temp roots | AC-P1-008–010 |
| Sessions | codec, resume, concurrency, replay, lifecycle, delete shim | AC-P1-011–015 |
| Stream/result/events | notification fixtures and fake/runtime parity | AC-P1-016–017, 021 |
| Usage/raw/errors | SDK result/error fixtures and redaction assertions | AC-P1-018–020 |
| Quota/quality | guarded default suite, coverage, lint, typing, build | AC-P1-022, 024 |

## Opt-In Real Runtime Validation

Prerequisites are an existing Codex-managed ChatGPT login, explicit quota authorization, and a
disposable test prompt/thread. Tests must not initiate login, print account email, or retain a
session descriptor in artifacts.

PowerShell:

```text
$env:PROTEO_CODEX_INTEGRATION = "1"
uv run pytest -m integration tests/integration/codex -q
Remove-Item Env:PROTEO_CODEX_INTEGRATION
```

POSIX shell:

```text
PROTEO_CODEX_INTEGRATION=1 uv run pytest -m integration tests/integration/codex -q
```

The suite validates account mode/catalog without PII, one minimal brain call, stream completion,
persistent create/resume, and archive/delete cleanup. An interruption case runs only when its
fixture can guarantee an active turn; otherwise unit evidence remains authoritative and the skip
reason is recorded.

## Compatibility Matrix

CI runs the quota-safe suite, type/lint/import checks, build, and artifact inspection on Linux
and Windows for Python 3.11–3.14. Real-runtime tests are never part of pull-request or default CI.
Before completion, run the opt-in smoke suite once on a supported local platform with
`openai-codex>=0.147,<0.148`.

## Evidence Record

Pending. Record date, commit, OS, Python, exact SDK version, commands, test counts, coverage,
artifact names, CI URLs, and sanitized integration results. A skipped required scenario is not
acceptance evidence unless this document explicitly identifies an approved blocker.
