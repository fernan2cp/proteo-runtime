# ERRATA — Controlled Agent Lifecycle Semantics

**Date:** 2026-09-18  
**Applies to:** `docs/plans/complete/controlled-agent-lifecycle-semantics/`  
**Design authority:** `docs/design/project-guide.md`  
**Status:** Post-implementation hardening errata. The implementation changes described here were applied locally by the maintainer and were not yet available in the remote repository at the time this document was prepared.

---

## 1. Purpose

This document records corrections and hardening decisions identified during a post-implementation audit of the `controlled_turn` / `controlled_agent` lifecycle work after the original SDD package had been marked complete.

The original SDD remains the historical design record. This errata does **not** replace the core architecture and does **not** introduce a new execution model. It clarifies and strengthens guarantees that were already intended by the plan but were found to be incompletely enforced, insufficiently tested, or too broadly stated in the completed package.

At the time this errata was prepared, the corresponding implementation changes had been applied in a **local working tree** but were not yet available in the remote GitHub branch. Therefore, this document distinguishes between:

- **Corrected design requirement:** authoritative clarification introduced by this errata.
- **Local implementation status:** reported as implemented locally by the maintainer.
- **Remote verification status:** pending until the implementation is pushed and the relevant tests/CI can be inspected.

Where this document conflicts with a narrower interpretation in the archived SDD, **this ERRATA takes precedence**.

---

## 2. Unchanged architectural baseline

The following core decisions remain unchanged:

- `controlled_turn` is invocation-scoped, ephemeral, uses `ContextPolicy.EXTERNAL`, and is created through `runtime.model(...)`.
- `controlled_agent` is task-scoped, ephemeral, uses `ContextPolicy.RUNTIME`, and is created through `runtime.task(...)`.
- `controlled_agent` reuses one live provider context across sequential turns within a `RuntimeTask`.
- `RuntimeTask` remains non-durable and non-resumable after closure.
- `session` remains the persistent/resumable lifecycle abstraction.
- Host tools remain runtime-controlled and fail closed.
- `task_id`, `turn_id`, and `invocation_id` remain provider-neutral correlation identifiers.

The corrections below harden lifecycle ownership, authority immutability, cleanup, privacy, factory boundaries, and validation evidence around that baseline.

---

## 3. ERR-CAL-001 — Raw provider thread identifiers are strictly internal

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-021`
- `05_validation_plan.md` — `SCEN-030`
- `README.md` — Observability & Tool Event Correlation

### Problem identified

The implementation could expose the raw Codex provider thread identifier inside public invocation metadata. Because neutral runtime events may be consumed by observers such as LangSmith or other integrations, this violated the intended provider-neutral observability boundary.

### Corrected requirement

Raw provider thread identifiers are **provider-private implementation details** and MUST NOT appear in:

- `RuntimeEvent` public metadata;
- `RuntimeResult`;
- LangSmith metadata;
- OpenTelemetry public attributes;
- LangGraph event projection;
- other provider-neutral telemetry or public runtime surfaces.

External correlation MUST use Proteo-owned identifiers such as:

- `task_id`;
- `turn_id`;
- `invocation_id`;
- provider-neutral `session_id` where applicable.

Provider thread identifiers may continue to exist internally for provider routing, lifecycle management, deletion, persistence mechanics, or compatibility bridges.

### Validation correction

`SCEN-030` must include an explicit canary test proving that a known internal provider thread identifier cannot escape through any public event, result, or observability adapter.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 4. ERR-CAL-002 — Turn startup and task teardown must be atomic with respect to lifecycle ownership

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-010`, `AC-CAL-011b`, `AC-CAL-014`
- `05_validation_plan.md` — `SCEN-019`, `SCEN-023b`, `SCEN-024`
- `README.md` — State Machine & Idempotent Teardown Flow

### Problem identified

The original implementation checked `OPEN` before provider turn creation, but there was a window in which `close()` could transition the task to `CLOSING` and tear down provider resources while a concurrent `_start_turn()` was still awaiting provider turn creation and had not yet registered `_active_run`.

The prior validation that forced `TaskState.CLOSING` manually proved state rejection, but did not prove the actual startup-versus-close race.

### Corrected requirement

The transition:

```text
validate OPEN
-> reserve turn ownership
-> start provider turn
-> register active run
```

must be synchronized with:

```text
OPEN
-> CLOSING
-> teardown
-> CLOSED
```

such that:

1. once `CLOSING` begins, no new turn can acquire lifecycle ownership;
2. a turn that has already acquired startup ownership is visible to teardown even if provider turn creation has not yet completed;
3. provider resources cannot be destroyed underneath an in-flight turn startup;
4. concurrent `close()` calls remain idempotent;
5. `TASK_CLOSED` is emitted exactly once.

### Validation correction

`SCEN-023b` and `SCEN-024` must use a deterministic concurrent test with a controllable async barrier/event inside provider `thread.turn()` or equivalent startup logic. Manually assigning `_state = CLOSING` is not sufficient evidence of race safety.

Equivalent coverage should exist for both `ainvoke()` and `astream()` where their startup paths differ materially.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 5. ERR-CAL-003 — Runtime shutdown must close dependent tasks before provider SDK teardown

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-014`, `AC-CAL-014b`
- `05_validation_plan.md` — `SCEN-016`, `SCEN-024`
- `06_rollout_and_rollback.md` — runtime teardown assumptions

### Problem identified

`CodexRuntime.close()` could close the provider SDK before invoking task-level teardown. However, `_CodexTask.close()` still requires the provider SDK to release/delete provider thread resources. Cleanup exceptions could also be suppressed, hiding this ownership inversion.

### Corrected requirement

Runtime shutdown must respect reverse dependency order.

At minimum:

1. reject/block new runtime work;
2. close active `RuntimeTask` instances while provider transport/SDK is still operational;
3. complete remaining run/session cleanup according to ownership;
4. unregister/close provider tool routing infrastructure;
5. close the provider SDK/transport;
6. finalize runtime-owned registries and observability.

Best-effort cleanup remains required, but later cleanup steps must continue if an earlier task fails.

### Validation correction

Tests must record teardown ordering and prove that provider thread deletion/release occurs **before** `sdk.close()`.

A multi-task failure test must also prove that one failed task cleanup does not prevent cleanup of other tasks or final SDK shutdown.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 6. ERR-CAL-004 — Task authority freezing includes executor security semantics, not only tool schemas

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-015`
- `05_validation_plan.md` — `SCEN-025`
- `README.md` — Semantic Configuration & Authority Freezing

### Problem identified

The original design correctly froze `ToolSnapshot`, but a task could still retain a caller-owned mutable `ToolExecutor`. Mutating security-relevant executor fields after task creation could theoretically widen task authority even though the tool schema snapshot itself was fixed.

### Corrected requirement

Authority freezing is defined over the **complete task execution authority**, including every security-relevant semantic that can affect what the task may execute.

After task creation:

```text
authority(task, future turn) <= authority(task, creation)
```

The task MUST NOT gain authority because an external caller mutates objects retained by reference.

The frozen authority boundary includes, as applicable:

- tool definitions/schema snapshot;
- executable/callable binding set;
- permission policy;
- approval policy;
- retry/failure policy where it affects execution authority;
- other security-relevant executor configuration.

The implementation may use immutable snapshots, task-scoped bindings, immutable executor security fields, or an equivalent mechanism, but caller-held mutable state must not expand a live task's authority.

### Validation correction

`SCEN-025` must test both:

1. mutation/addition of tools in the original registry after task creation;
2. attempted mutation/replacement of security-relevant executor policy after task creation.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 7. ERR-CAL-005 — Factory boundaries use positive lifecycle/context matching, including custom profiles

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-008b`
- `05_validation_plan.md` — `SCEN-009`, `SCEN-010`, `SCEN-011`
- `README.md` — Symmetric Factory Lifecycle Boundaries

### Problem identified

The built-in profile behavior matched the intended architecture, but portions of the implementation enforced factory ownership through negative exclusions rather than requiring the exact positive lifecycle/context combination. This left room for custom profile combinations to enter a factory that did not semantically own them.

### Corrected requirement

Factory eligibility is defined by positive semantic predicates, not merely by rejecting known built-in profiles.

Unless a separately documented special case exists:

```text
runtime.model(...)
  requires LifecycleMode.EPHEMERAL
  and ContextPolicy.EXTERNAL

runtime.task(...)
  requires LifecycleMode.EPHEMERAL
  and ContextPolicy.RUNTIME

runtime.session(...)
  requires LifecycleMode.PERSISTENT
  and an explicitly supported persistent context policy
```

Custom profiles are subject to the same lifecycle/context boundaries as built-in profiles.

No factory may silently coerce an incompatible profile into another lifecycle abstraction.

### Validation correction

Factory tests must include a matrix of custom profile combinations, including at least:

- `EPHEMERAL + EXTERNAL`;
- `EPHEMERAL + RUNTIME`;
- `EPHEMERAL + EXPLICIT`;
- `PERSISTENT + RUNTIME`;
- `PERSISTENT + HYBRID`;
- `PERSISTENT + EXTERNAL`.

The same semantic validation must hold for `CodexRuntime` and `FakeRuntime`.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 8. ERR-CAL-006 — `ToolExecutor.end_invocation()` applies to `controlled_turn` as well as task turns

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-017`
- `05_validation_plan.md` — `SCEN-028`
- `README.md` — Tool Execution Finalization

### Problem identified

The completed SDD described `ToolExecutor.end_invocation(invocation_id)` primarily in the `RuntimeTask` lifecycle. `controlled_turn` also creates invocation-scoped executor state, but its cleanup path did not consistently finalize that state.

This could retain per-invocation deduplication/locking data when a tool-enabled `RuntimeModel` was reused across multiple `controlled_turn` calls.

### Corrected requirement

`ToolExecutor.end_invocation(invocation_id)` is an **invocation lifecycle invariant**, not a `RuntimeTask`-only behavior.

For every invocation that allocates invocation-scoped executor state, including `controlled_turn`, finalization must occur exactly once after:

- normal completion;
- provider/tool failure;
- timeout;
- cancellation;
- stream completion;
- early stream close where supported.

Cleanup ownership must be unambiguous so the same invocation is not finalized twice.

### Validation correction

Add explicit `controlled_turn` tests proving exactly-once `end_invocation(invocation_id)` behavior across success and failure paths, and proving no completed invocation state remains in executor deduplication/lock structures.

`AC-CAL-017` and `SCEN-028` should therefore be read as applying to all tool-enabled invocation lifecycles, with task-specific teardown behavior remaining an additional requirement for `controlled_agent`.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 9. ERR-CAL-007 — Cleanup failures must be observable without aborting best-effort teardown

### Affected original material

- `04_acceptance_criteria.md` — `AC-CAL-014b`
- `05_validation_plan.md` — `SCEN-023`, `SCEN-024`
- `README.md` — State Machine & Idempotent Teardown Flow

### Problem identified

Several task cleanup stages used broad exception suppression. This preserved best-effort teardown but could make failures invisible, contrary to the SDD's stated requirement that cleanup failures be diagnostically observable.

### Corrected requirement

Cleanup remains best effort:

```text
failure in cleanup step N
!= abort cleanup steps N+1 ...
```

However, every significant cleanup failure must produce a safe diagnostic signal.

Diagnostics must:

- identify the cleanup phase with a stable low-cardinality code/category;
- avoid leaking arbitrary provider exception text, credentials, raw payloads, provider thread IDs, or other sensitive state;
- allow remaining cleanup to continue;
- leave the task in `CLOSED` and unusable state;
- preserve exactly-once `TASK_CLOSED` semantics.

Examples of diagnostic categories may include provider deletion failure, invocation cleanup failure, route cleanup failure, or workspace cleanup failure, following the project's existing diagnostic naming conventions.

### Validation correction

Inject failures independently and in combination across cleanup stages and prove that:

- later cleanup still executes;
- the task reaches `CLOSED`;
- task registry removal still occurs;
- `TASK_CLOSED` is emitted once;
- a sanitized diagnostic is emitted;
- secret/raw exception content is not exposed;
- a second `close()` remains a safe no-op.

### Status

- Corrected design requirement: **accepted**.
- Local implementation: **reported implemented**.
- Remote verification: **pending push / CI inspection**.

---

## 10. Validation-status correction for the completed SDD

The original package was archived as complete and states that architectural gaps were closed. That statement should now be interpreted as:

> The primary lifecycle architecture and API decisions were complete, but subsequent implementation-level audit identified hardening gaps in enforcement and validation evidence.

Accordingly, the completed SDD should **not** be treated as proof that every lifecycle guarantee was already demonstrated by automated tests at the time it was archived.

Final closure after this errata requires remote evidence that:

1. all seven corrections above are present in the pushed implementation;
2. deterministic concurrency tests exercise the real startup/close race;
3. provider thread identifiers are absent from public observability surfaces;
4. runtime shutdown ordering respects provider ownership;
5. task authority cannot be expanded through caller-owned mutable objects;
6. factory-boundary tests cover custom profile combinations;
7. `controlled_turn` finalizes invocation-scoped executor state exactly once;
8. cleanup failures emit sanitized diagnostics while teardown continues;
9. mandatory offline verification passes;
10. repository CI reaches and passes the relevant test suites rather than failing earlier in formatting/type-check gates.

The optional live Codex integration smoke test remains useful provider evidence but is not a substitute for deterministic offline lifecycle tests.

---

## 11. Traceability summary

| Errata ID | Primary concern | Existing criteria/scenarios refined |
|---|---|---|
| `ERR-CAL-001` | Provider ID privacy | `AC-CAL-021`, `SCEN-030` |
| `ERR-CAL-002` | Startup/close race safety | `AC-CAL-010`, `AC-CAL-011b`, `AC-CAL-014`, `SCEN-019`, `SCEN-023b`, `SCEN-024` |
| `ERR-CAL-003` | Runtime shutdown ownership order | `AC-CAL-014`, `AC-CAL-014b`, `SCEN-016`, `SCEN-024` |
| `ERR-CAL-004` | Frozen execution authority | `AC-CAL-015`, `SCEN-025` |
| `ERR-CAL-005` | Exact factory semantic boundaries | `AC-CAL-008b`, `SCEN-009`, `SCEN-010`, `SCEN-011` |
| `ERR-CAL-006` | Invocation finalization for `controlled_turn` | `AC-CAL-017`, `SCEN-028` |
| `ERR-CAL-007` | Observable resilient cleanup | `AC-CAL-014b`, `SCEN-023`, `SCEN-024` |

---

## 12. Relationship to SDD completion state

This errata does not reopen the fundamental design choice between `controlled_turn`, `controlled_agent`, and `session`.

It does, however, amend the meaning of **complete** for this plan:

- **Architecture:** remains accepted.
- **Primary public API:** remains accepted.
- **Lifecycle model:** remains accepted.
- **Hardening corrections described in this ERRATA:** accepted and reported implemented locally.
- **Automated verification of the corrected implementation:** pending inspection after the local changes are pushed.
- **Final evidence-backed closure:** should be claimed only after the corrected test suite and CI pass.

---

## 13. Recommended verification gate after pushing the local implementation

Run the mandatory offline suite and any targeted lifecycle tests added by these corrections. At minimum:

```bash
uv run ruff check src tests examples
uv run ruff format --check src tests examples
uv run mypy src
uv run lint-imports
uv run pytest tests/unit -v
uv run pytest examples/smart_quote_agent -v
```

Additionally, the corrected implementation should have targeted tests covering:

- raw provider ID non-leakage;
- real startup-versus-close concurrency;
- task cleanup before SDK shutdown;
- immutable task authority;
- custom-profile factory matrices;
- exactly-once `controlled_turn` invocation cleanup;
- sanitized diagnostics during cleanup failures.

The optional live Codex integration suite can then be executed as an additional provider-level smoke test.

---

## 14. Historical note

This ERRATA exists specifically to preserve the original completed SDD as a historical design artifact while recording implementation-level corrections discovered after its initial closure. Future readers should evaluate the lifecycle contract using the original SDD **plus this ERRATA**, rather than silently rewriting the archived design record.
