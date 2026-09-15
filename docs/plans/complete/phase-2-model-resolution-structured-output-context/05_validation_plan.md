# Validation Plan — Phase 2

## Quality Gates

Run from the repository root after implementation and after documentation/evidence updates:

```text
uv run pre-commit run --all-files
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run lint-imports
```

Do not relax configuration, add blanket ignores, or exclude new branches to satisfy a gate.

## Default Quota-Safe Validation

```text
uv run pytest -q
uv run pytest --cov=proteo_runtime --cov-report=term-missing --cov-fail-under=90 -q
```

All configuration, catalog, schema, structured retry, event, context, resume, and migration tests
use SDK doubles or `FakeRuntime`. A contract guard must fail the suite if a default test constructs
real `AsyncCodex`, reads Codex authentication, accesses a network, or omits the integration gate.

## Focused Test Matrix

| Area | Required scenarios | Criteria |
|---|---|---|
| JSON sources | UTF-8, env/explicit precedence, absent/unreadable/malformed, no cwd discovery | AC-P2-002–003 |
| Schema/config | unknown paths, version/runtime, deep freeze, profile cross-references/compositions | AC-P2-003–004, 008 |
| Defaults/resolver | packaged matrix, artifact inclusion, missing catalog/effort/level, no fallback | AC-P2-005–007 |
| Concurrency | bound + call overrides, parallel calls, no sticky mutation | AC-P2-005 |
| Schema binding | Pydantic class, Draft 2020-12 dict, caller immutability, invalid kinds/meta-schema | AC-P2-010–013 |
| Structured retry | first success, retry success, exhaustion, max attempts, safe feedback, non-retry errors | AC-P2-014–016, 018 |
| Structured stream | buffered deltas, one invocation ID/result, attempt turn IDs, usage sum, monotonic sequence | AC-P2-015, 017 |
| Context | external role history, runtime user-only, hybrid system/user, assistant/tool rejection | AC-P2-019–020 |
| Sessions | mapped create/resume, fingerprints, opaque descriptor, lock/interrupt/cleanup | AC-P2-021–022 |
| Migration | same thread/new descriptor, event, old handles, failure matrix, no destructive operations | AC-P2-023–025 |
| Capabilities | executable structure and explicit rejection of every deferred feature | AC-P2-008, 026 |
| Boundaries/quota | public exports/protocols, import contract, real-runtime guard | AC-P2-009, 027 |

## Real Codex Integration

Prerequisites are an existing Codex-managed ChatGPT login, explicit subscription-quota
authorization, a catalog compatible with the packaged v1 mappings, and disposable content.
Integration tests remain marked `integration` and skipped by default.

PowerShell execution:

```text
$env:PROTEO_CODEX_INTEGRATION = "1"
uv run pytest -m integration tests/integration/codex -q
Remove-Item Env:PROTEO_CODEX_INTEGRATION
```

The opt-in suite must verify:

- all packaged model/effort mappings remain visible;
- one Pydantic and one dictionary-schema invocation are provider- and host-validated;
- structured streaming exposes only buffered validation/retry/terminal semantics;
- one disposable persistent thread resumes and migrates under a new target mapping;
- cleanup deletes only the disposable integration thread created by that test.

Evidence records pass/fail counts, SDK/package versions, and safe model identifiers. It must not
record identity metadata, opaque session descriptors, prompts, structured values, invalid raw
output, or credentials.

## Packaging and Isolated Artifact Validation

```text
uv build
uv run python scripts/check_artifacts.py dist
```

Install the wheel and sdist separately into clean temporary environments and verify:

- `proteo-runtime --version` and `python -m proteo_runtime --version` report `0.3.0`;
- `jsonschema` is installed as a base dependency;
- packaged Codex defaults load without a checkout or working-directory assumptions;
- public imports include `StructuredOutputPolicy` and `ProfileConfig`;
- importing `proteo_runtime` does not import Codex or framework packages.

## CI Evidence

Required remote evidence is one successful workflow for pre-commit/static checks, package tests
with branch-aware coverage >=90 percent, builds, artifact inspection, and isolated installs on
Ubuntu and Windows with Python 3.11, 3.12, 3.13, and 3.14. Real Codex integration remains excluded
from default CI. Run `34941152369` on the pushed phase-2 branch passed all nine matrix/packaging
jobs; URL: https://github.com/fernan2cp/proteo-runtime/actions/runs/34941152369.

## Evidence Recording

Replace pending task evidence only with command, test, CI-run, or reviewed-artifact evidence.
Record known pre-existing failures separately and prove that no Phase 2 failure is hidden by them.
Do not mark the SDD complete until all `AC-P2-*` entries are satisfied.

## Local Evidence — 2026-09-15

- `pytest -q`: **60 passed, 4 skipped** (integration remains opt-in).
- `pytest -q --cov=proteo_runtime --cov-report=term-missing --cov-fail-under=90`:
  **90.12% branch-aware coverage**, passed.
- `ruff format --check src tests`, `ruff check src tests`, `mypy src tests`, and
  `lint-imports`: passed.
- `pre-commit run --all-files`: passed (ruff format/check, whitespace, YAML, and TOML hooks).
- `PROTEO_CODEX_INTEGRATION=1 pytest -m integration tests/integration/codex -q`: **4 passed**;
  disposable session cleanup completed.
- `uv build` produced `proteo_runtime-0.3.0-py3-none-any.whl` and
  `proteo_runtime-0.3.0.tar.gz`; `scripts/check_artifacts.py dist` passed.
- Wheel and sdist installed into separate clean Python 3.11 environments; version, CLI, base
  `jsonschema`, and packaged mappings all validated.

Remote CI evidence was intentionally pending at the historical capture point; subsequent
conformance CI evidence is recorded in the Phase 2.1 remediation SDD and does not replace the
historical local evidence above.
