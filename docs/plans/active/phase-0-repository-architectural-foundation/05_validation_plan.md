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
uv run pytest tests -q \
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

The following results were executed after the Phase 0 fixes; historical partial results are superseded.

### Quality gates

| Command | Result | Evidence |
|---|---|---|
| `uv run pre-commit run --all-files` | PASS (0) | Ruff format/lint, whitespace, EOF, YAML, and TOML hooks passed. |
| `uv run ruff format --check .` | PASS (0) | 42 files already formatted. |
| `uv run ruff check .` | PASS (0) | All checks passed, including UP038. |
| `uv run mypy src tests` | PASS (0) | No issues in 40 source/test files. |
| `uv run lint-imports` | PASS (0) | 41 files analyzed; 1 contract kept, 0 broken. |

### Tests and coverage

`uv run pytest tests -q --cov=proteo_runtime --cov-report=term-missing --cov-fail-under=90` completed with **29 passed, 0 failed, 91.21% total coverage** on Windows Python 3.11.4. The same suite passed on Windows Python 3.12.14, 3.13.15, and 3.14.7, and on Linux Docker Python 3.11.14, 3.12.12, 3.13.11, and 3.14.2. The suite includes unit, protocol, public API, import-boundary, fake-runtime, configuration, session codec, CLI, and quota-safety tests.

### Packaging and CLI

- `uv build` (exit 0) produced `dist/proteo_runtime-0.1.0-py3-none-any.whl` and `dist/proteo_runtime-0.1.0.tar.gz`.
- `uv run python scripts/check_artifacts.py dist` (exit 0) verified package files, `py.typed`, metadata, license, entrypoint, and absence of caches/credential-shaped paths.
- Each artifact was installed into a fresh uv Python 3.11 environment (exit 0). `import proteo_runtime` reported `0.1.0`; `proteo-runtime --version` and `python -m proteo_runtime --version` each reported `0.1.0`.
- Reviewed package tree: wheel contains `proteo_runtime` modules, `py.typed`, `.dist-info/METADATA`, `WHEEL`, `entry_points.txt`, and license; sdist contains source package, `pyproject.toml`, README, and license without local caches.
- Reviewed root exports: explicit `__all__` contains `__version__` plus the documented provider-neutral contracts, errors, policies, profiles, events, and value objects. `SessionCodec`, fake implementations, provider SDK types, and internal modules are not root exports.

### Quota safety

No real Codex runtime was used. Default tests passed with guards that fail on `openai_codex` imports, network sockets, provider subprocesses, credential-path reads, and credential-shaped environment access. The default suite used no ChatGPT/Codex login, API keys, network requests, provider subprocesses, or subscription quota.

### CI matrix

The workflow now defines `push`, `pull_request`, and `workflow_dispatch`, `fail-fast: false`, Ubuntu/Windows Python 3.11–3.14, pre-commit/static gates, full coverage tests, builds, and an isolated packaging/artifact job. No GitHub Actions run URL exists yet: the branch is not published and the local `gh` client is unauthenticated. Remote CI validation is therefore **pending**, and P0-TASK-0010/P0-TASK-0011 remain `in_progress`.

### Deferred or blocked items

- Remote GitHub Actions matrix and packaging job: blocked pending repository publication/CI credentials; owner is the release engineer, to be completed before handoff.
- Codex provider, configuration loading/precedence, LangGraph/LangSmith/OpenTelemetry integrations, tool execution, exporters, OS sandbox enforcement, and real authentication remain deferred to their documented later phases.
