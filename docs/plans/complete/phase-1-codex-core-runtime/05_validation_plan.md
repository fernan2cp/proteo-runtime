# Validation Plan — Phase 1

## Quality Gates

Run from the repository root:

```text
uv run pre-commit run --all-files
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run lint-imports
```

The final local run is required after documentation updates and after any CI correction. The
pre-commit configuration is not relaxed and no blanket type ignores or coverage exclusions are
used.

## Default Quota-Safe Validation

```text
uv run pytest -q
uv run pytest --cov=proteo_runtime --cov-report=term-missing --cov-fail-under=90 -q
```

The default suite installs an SDK double before constructing the provider. It does not construct
real `AsyncCodex`, read Codex authentication, access a network, start login, or consume
subscription quota. Integration tests are marked `integration` and skip unless
`PROTEO_CODEX_INTEGRATION=1`.

## Local Evidence

| Command | Result |
|---|---|
| `uv run ruff format --check src tests` | Passed; 48 files formatted. |
| `uv run ruff check src tests` | Passed. |
| `uv run mypy src tests` | Passed; no issues in 48 source files. |
| `uv run lint-imports` | Passed; 1 contract kept and 0 broken. |
| `uv run pytest -q` | 46 passed, 3 skipped after the streaming smoke was added. |
| `uv run pytest --cov=proteo_runtime --cov-report=term-missing --cov-fail-under=90 -q` | 46 passed, 3 skipped; 90.38% branch-aware total coverage. |
| `uv build` | Built `proteo_runtime-0.2.0-py3-none-any.whl` and `proteo_runtime-0.2.0.tar.gz`. |
| `uv run python scripts/check_artifacts.py dist` | Passed; exactly one wheel and one sdist, with no unsafe paths. |
| isolated wheel/sdist import and CLI checks | Passed; import, `proteo-runtime --version`, and `python -m proteo_runtime --version` report 0.2.0. |

## Focused Test Areas

| Area | Evidence | Criteria |
|---|---|---|
| Provider boundary/lifecycle | SDK factory double, restart, context manager, partial-start cleanup | AC-P1-002–003 |
| Authentication/identity | nested/direct account fixtures, ChatGPT-only validation, redaction | AC-P1-004–005 |
| Catalog/resolution | hidden filtering, default cardinality, effort-option mapping and rejection | AC-P1-006–007 |
| Brain/security | deterministic input, ephemeral thread, empty workspace, read-only sandbox, deny-all approval | AC-P1-008–010 |
| Sessions | descriptor, provider resume, shared locks, replay policy, close/archive/delete, migration rejection | AC-P1-011–015 |
| Stream/result/events | real notification names, deltas, terminal result parity, failed/interrupted/fallback streams | AC-P1-016–017, 021 |
| Usage/raw/errors | token aliases, duration, sanitized raw mapping, timeout/cancellation/transport mapping | AC-P1-018–020 |
| Quota/quality | guarded suite, coverage, lint, typing, import boundary, packaging | AC-P1-022, 024 |

## Real Codex Integration

Prerequisites were an existing Codex-managed ChatGPT login, explicit quota authorization, and
disposable prompts/threads. Tests do not initiate login, print account email, or retain session
descriptors in artifacts.

PowerShell command executed:

```text
$env:PROTEO_CODEX_INTEGRATION = "1"
uv run pytest -m integration tests/integration/codex -q
Remove-Item Env:PROTEO_CODEX_INTEGRATION
```

Evidence: 3 tests passed, 0 failed, 0 skipped. The run covered catalog/brain invocation,
normalized streaming, and persistent session create/turn/close/resume/archive/delete. No
credentials or session descriptor were written to artifacts or output.

## CI Evidence

The workflow is configured for `push`, `pull_request`, and `workflow_dispatch` with
`fail-fast: false`, Ubuntu and Windows Python 3.11–3.14, static checks, quota-safe tests with
coverage >=90%, build, packaging, and isolated 0.2.0 checks. Real integration remains excluded
from default CI.

Remote run: [GitHub Actions CI run 34931792468](https://github.com/fernan2cp/proteo-runtime/actions/runs/34931792468)
for commit `770aca1b1b7899fbee10fe20d121b151b6346c9d`; conclusion `success`.

| Job | Result |
|---|---|
| Pre-commit / static quality | PASS |
| Ubuntu / Python 3.11 | PASS |
| Ubuntu / Python 3.12 | PASS |
| Ubuntu / Python 3.13 | PASS |
| Ubuntu / Python 3.14 | PASS |
| Windows / Python 3.11 | PASS |
| Windows / Python 3.12 | PASS |
| Windows / Python 3.13 | PASS |
| Windows / Python 3.14 | PASS |
| Packaging and isolated artifacts | PASS |

The run validated installation, Ruff format/lint, mypy, import-linter, quota-safe tests with the
coverage gate, wheel/sdist builds, artifact inspection, and isolated wheel/sdist import and CLI
checks. No integration credentials were configured in CI.
