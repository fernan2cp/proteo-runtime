# Validation Plan — Phase 0

## Local Setup

Use a clean Python 3.11–3.14 environment and run:

```bash
uv sync --extra dev
uv run pre-commit run --all-files
```

The validation must be repeatable without Codex login, API keys, a Codex executable, or network access after dependencies are installed.

## Packaging Checks

```bash
uv build
uv run pip install --force-reinstall dist/*.whl
uv run python -c "import proteo_runtime; print(proteo_runtime.__version__)"
uv run proteo-runtime --version
uv run python -m proteo_runtime --version
```

Verify the wheel and sdist contain the package, `py.typed`, license metadata, and no local credentials or development-only files.

## Static Quality Checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run lint-imports
```

The import-boundary check must explicitly exercise the core package in an environment where optional integration packages are absent.

## Unit and Contract Checks

```bash
uv run pytest tests/unit tests/contract -q \
  --cov=proteo_runtime \
  --cov-report=term-missing \
  --cov-fail-under=90
```

Required scenario groups:

1. Input/value objects: string normalization, message roles, immutability, invalid values, and arbitrary-object rejection.
2. Public protocols: fake implementations satisfy runtime/model/session contracts without provider types.
3. Profiles/policies: vocabulary, safe defaults, and capability metadata.
4. Errors: hierarchy, cause chaining, stable attributes, and secret-safe rendering.
5. Configuration: valid schema v1, unknown-key paths, unsupported version, invalid level, immutable mappings, and missing mapping failures.
6. Session codec: deterministic encoding, round trip, malformed payloads, unsupported version, required fields, secret-field rejection, and permission non-expansion.
7. Fake runtime: lifecycle, scripted invocation, ordered stream, usage, diagnostics, session close/resume, interruption, cancellation, injected failures, and `SessionBusyError`.
8. CLI: version output and no provider startup.

## Quota-Safety Checks

The default test command must include guards that:

- fail if `openai_codex` is imported by core or fake-runtime modules;
- fail if subprocess creation or network sockets are attempted by default tests;
- verify no authentication files or environment secrets are read;
- run successfully with Codex unavailable and without `OPENAI_API_KEY` or ChatGPT login.

Real Codex tests are out of scope and must not be added to the default command. Future provider tests must use `pytest -m integration` and an explicit opt-in.

## CI Matrix

GitHub Actions must run on `ubuntu-latest` and `windows-latest` for Python 3.11, 3.12, 3.13, and 3.14. The matrix must execute installation, unit/contract tests, lint/type/import checks, and a build artifact job. CI must fail on any test, coverage, dependency-boundary, or packaging error.

## Evidence Record

`03_task_plan.md` task completion must link to:

- command and exit status;
- test count and coverage result;
- CI workflow run and OS/Python matrix;
- reviewed package tree and public export list;
- any deferred or blocked item with owner and follow-up phase.

The final validation record must state explicitly that no real Codex runtime was used.
## Recorded Evidence

- Windows Python 3.11: `uv sync --locked --extra dev`, 20 tests passed, coverage 90.81%, Ruff, mypy, and import-linter passed.
- Packaging: `uv build` produced `proteo_runtime-0.1.0-py3-none-any.whl` and `proteo_runtime-0.1.0.tar.gz`; each installed into an isolated environment and both CLI entrypoints printed `0.1.0`; `py.typed` and metadata were present.
- Linux Python 3.11 Docker: dependency installation, 20 tests, Ruff, mypy, and import-linter passed. The container was discarded before its final `uv build` because the mounted Windows worktree made the sdist scan hang.
- No test imported `openai_codex` or accessed authentication, network sockets, subprocesses, or subscription quota. Remote GitHub Actions evidence is pending publication, so this SDD remains under `docs/plans/active/`.
