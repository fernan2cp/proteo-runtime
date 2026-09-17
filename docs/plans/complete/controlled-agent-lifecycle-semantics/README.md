# SDD Package — Controlled Agent Lifecycle Semantics

- **Plan Directory**: `docs/plans/active/controlled-agent-lifecycle-semantics/`
- **Status**: Active (Decision-Complete, Ready for Implementation)
- **Design Authority**: `docs/design/project-guide.md`
- **Related ADRs**: ADR 0001, ADR 0003, ADR 0004

---

## 1. Executive Summary

This Software Design Document (SDD) package establishes the definitive architecture, requirements, tasks, acceptance criteria, and validation plans for **Controlled Agent Lifecycle Semantics** in Proteo Runtime.

The design decouples "ephemeral durability" from "turn count", introducing two first-class, built-in controlled execution profiles:
1. **`controlled_turn`**: Invocation-scoped, one-shot execution with external context and controlled tools. Starts from a clean runtime context on every call, preserving the single-invocation behavior previously associated with `controlled_agent`.
2. **`controlled_agent`**: Task-scoped, stateful ephemeral execution with runtime-owned context and controlled tools. Reuses the identical live provider thread across all turns within an explicitly bounded `RuntimeTask`, discarding all runtime state upon task closure.

---

## 2. Profile Specifications Matrix

| Dimension | `controlled_turn` | `controlled_agent` |
|---|---|---|
| **Lifecycle** | `LifecycleMode.EPHEMERAL` (invocation-scoped) | `LifecycleMode.EPHEMERAL` (task-scoped) |
| **Context Policy** | `ContextPolicy.EXTERNAL` (host manages history) | `ContextPolicy.RUNTIME` (runtime manages local conversation) |
| **Host Tools Mode** | `HostToolsMode.CONTROLLED` (explicit registry) | `HostToolsMode.CONTROLLED` (explicit registry) |
| **Security Policy** | `SecurityPolicy.CONTROLLED_TOOLS` (fail-closed host execution) | `SecurityPolicy.CONTROLLED_TOOLS` (fail-closed host execution) |
| **Provider Thread Reuse** | Clean thread per invocation; zero cross-call memory | Single live provider thread reused across all turns in task |
| **Durability / Resume** | None (ephemeral invocation) | None (discarded on task close; strictly non-resumable) |
| **Factory Interface** | `runtime.model(profile="controlled_turn", ...)` (synchronous) | `await runtime.task(profile="controlled_agent", registry=reg, executor=exec, ...)` (asynchronous) |

---

## 3. Symmetric Factory Lifecycle Boundaries

The Proteo Runtime API enforces strict, symmetric factory boundaries at call time without silent fallback or hidden state:

| Factory Method | Calling Convention | Permitted Context Policy | Permitted Lifecycle | Target Profiles | Fail-Fast Rejection Behavior |
|---|---|---|---|---|---|
| `runtime.model(...)` | Synchronous (`def`) | `ContextPolicy.EXTERNAL` | `LifecycleMode.EPHEMERAL` | `brain`, `structured`, `controlled_turn` | Calling with `controlled_agent`, `session`, or `native` raises `CapabilityError`. |
| `runtime.task(...)` | Asynchronous (`async def`) | `ContextPolicy.RUNTIME` | `LifecycleMode.EPHEMERAL` | `controlled_agent` | Calling with `controlled_turn`, `brain`, or `session` raises `CapabilityError`. |
| `runtime.session(...)` | Asynchronous (`async def`) | `ContextPolicy.RUNTIME` or `HYBRID` | `LifecycleMode.PERSISTENT` | `session` | Calling with `controlled_agent` or `controlled_turn` raises `CapabilityError`. |

---

## 4. Key Architectural Decisions (Decision-Complete)

1. **Synchronous `runtime.model(...)`**: In strict adherence to the existing Proteo `Runtime` contract, `runtime.model(...)` is synchronous (`def model(...)`). Callers do not use `await`.
2. **Mandatory Host Tool Bindings for `controlled_agent`**: `controlled_agent` profile strictly mandates a host tool registry (`registry` is mandatory; `executor` is optional, defaulting to a compatible `ToolExecutor(snapshot)` if omitted). `Runtime.task()` enforces an explicit entry guard (`if registry is None: raise CapabilityError(...)`) before delegating to `_tool_binding()`, prohibiting executor-only calls. Empty registries or mismatched executors fail fast with `CapabilityError` before starting any thread.
3. **Task-Scoped Instructions & Wire Translation**: Provided at task creation via `await runtime.task(instructions=...)`. Frozen for the life of the task; applies to all turns; caller does not resend per turn; exposed via read-only property `task.instructions`. Python callers invoke `start_thread(..., developer_instructions=instructions)`, and the private compatibility bridge (`experimental.start_thread()`) explicitly translates `developer_instructions -> developerInstructions` before constructing the raw wire request for the Codex App Server. Provider base instructions (`baseInstructions`) remain completely intact. `InvocationConfig` intentionally does NOT declare an `instructions` field, precluding per-turn mutation.
4. **Hardened Context Replay Protection (User-Only Input)**: `RuntimeTask.ainvoke()` and `astream()` accept `input: str | RuntimeInput`. Under `ContextPolicy.RUNTIME`, callers provide only `user` messages (or plain `str`). The neutral `RuntimeMessage` contract strictly admits `Literal["system", "user", "assistant", "tool"]` (`developer` is not a message role; per-turn developer instructions are prohibited and exist exclusively via `runtime.task(instructions=...)`). Supplying messages with role `system`, `assistant`, or `tool` fails before inference with `ContextPolicyError("Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; replaying 'assistant', 'tool', or injecting 'system' messages is prohibited.")`.
5. **Distinct Capability Flag & Provider Advertising**: `ephemeral_tasks: bool = False` added to `RuntimeCapabilities`, cleanly separating one-shot ephemeral sessions (`ephemeral_sessions`) from multi-turn ephemeral tasks (`ephemeral_tasks`). Runtime capability inspection uses `capabilities = await runtime.capabilities()`. `CodexRuntime.capabilities()` explicitly advertises `ephemeral_tasks=True` when provider capabilities are active, `FakeRuntime` advertises `ephemeral_tasks=True` by default for testing fidelity, and runtimes without task-scoped context support retain `ephemeral_tasks=False` (failing fast on `runtime.task(...)`).
6. **Active Task Registry & Non-Resumability Guard**: Owned in-memory by the runtime implementation (`runtime._tasks: dict[str, RuntimeTask[Any]]`). Tasks are assigned unique, opaque IDs (`f"task_{uuid.uuid4().hex}"`) that never leak provider thread IDs. Unregistered on `task.close()` or `runtime.close()`. Looking up unknown or closed IDs raises `SessionNotFoundError`. A `task_id` is never a `SessionDescriptor`; calling `runtime.resume_session()` with any identifier starting with `task_` triggers an explicit pre-codec guard raising `SessionNotFoundError("Task '{task_id}' is ephemeral and cannot be resumed as a session")`, preventing `SessionCodec.decode()` from misattributing lifecycle semantics to syntax/codec errors.
7. **Semantic Configuration & Authority Freezing**: Model, effort, security policy, tool registry snapshot, and instructions are permanently frozen at task start. `InvocationConfig` allows overriding only `timeout_seconds`, `include_raw`, and `metadata` per turn. Prohibited overrides raise `ConfigurationError` before inference.
8. **Observability & Tool Event Correlation**: `RuntimeEvent.task_id` defined in `events.py`; `RuntimeResult.task_id` defined in `model.py`; provider-neutral `ToolRequest.task_id: str | None = None` defined in `tools/__init__.py`. For `RuntimeTask` turns, `ToolRequest.task_id = RuntimeTask.id` and `ToolRequest.session_id = None`; the `ToolExecutor` event emission path (implemented via `_emit(...)`) propagates `request.task_id -> RuntimeEvent.task_id` across all emitted tool events (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_DENIED`, retries). `task_id` correlates all events, OpenTelemetry spans (`proteo.task_id`), and LangSmith metadata (`proteo_task_id`). `session_id` remains `None`. No raw provider thread IDs are emitted. Low-cardinality metric labels do not include `task_id`.
9. **Deterministic Error Taxonomy**: Strict error model with zero ambiguous alternatives:
   - Concurrency conflict: `SessionBusyError("Task already has an active turn")`.
   - Unknown/closed task: `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
   - Resuming ephemeral task: `SessionNotFoundError("Task '{task_id}' is ephemeral and cannot be resumed as a session")` (pre-codec guard).
   - Boundary/capability mismatch: `CapabilityError`.
   - Missing/invalid tool binding: `CapabilityError`.
   - Prohibited turn config override: `ConfigurationError`.
   - Replayed history or non-user turn role: `ContextPolicyError`.
10. **State Machine & Idempotent Teardown Flow**: `RuntimeTask` enforces an explicit state machine `OPEN -> CLOSING -> CLOSED`. Incoming calls to `ainvoke()`, `astream()`, or `interrupt()` that attempt to start after entering `CLOSING` fail immediately with `SessionNotFoundError("Task '{task_id}' not found or already closed")` before provider inference, preventing teardown races. During teardown, `close()` cancels any existing active turn directly via the internal provider/run cancellation primitive (e.g. `await active_run.interrupt()`), never calling the public `task.interrupt()` method and avoiding self-conflict. `close()` is strictly idempotent; concurrent `close()` calls do not duplicate cleanup, and `TASK_CLOSED` is emitted strictly once.
11. **Codex Subscription Authentication**: Live integration smoke test runs under subscription-backed authentication via Codex App Server / CLI login (`codex login`). Pre-flight check executes `await runtime.start()`, gracefully skipping via `pytest.skip` if `AuthenticationError` occurs. Zero reliance on `OPENAI_API_KEY` and zero invented SDK APIs.
12. **Smart Quote Agent Migration**: Migrates single-turn controlled reasoning in `examples/smart_quote_agent/app.py`, `graph.py`, `README.md`, and `tests/test_agent.py` to `profile="controlled_turn"`.
13. **ADR 0004 Synchronization**: Validates and synchronizes the existing accepted ADR `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md` via `CAL-TASK-0026`.
14. **Bounded Shared Engine**: Common mechanics between `_CodexTask` and `_CodexSession` are restricted strictly to turn execution, locking, streaming, and per-turn tool cleanup via `_StatefulContext`. Persistence, descriptors, resume, and task registries remain completely isolated.
15. **Tool Execution Finalization (`ToolExecutor.end_invocation`)**: `ToolExecutor.end_invocation()` contractually and exclusively takes `invocation_id` (`ToolExecutor.end_invocation(invocation_id)` at the end of every turn, and `ToolExecutor.end_invocation(active_invocation_id)` during task teardown). `turn_id` is never passed to `end_invocation()`.

---

## 5. Package Document Map

| Document | Purpose |
|---|---|
| [`00_baseline.md`](00_baseline.md) | Baseline context, repository state audit, and motivation. |
| [`01_requirements.md`](01_requirements.md) | Functional requirements (`CAL-REQ-001` through `CAL-REQ-026`, 35 items total). |
| [`02_technical_design.md`](02_technical_design.md) | Technical architecture, interface signatures, registry, and teardown mechanics. |
| [`03_task_plan.md`](03_task_plan.md) | Work breakdown structure (`CAL-TASK-0001` through `CAL-TASK-0027`, 28 tasks total), all `pending`. |
| [`04_acceptance_criteria.md`](04_acceptance_criteria.md) | Binary, testable acceptance criteria (`AC-CAL-001` through `AC-CAL-026`, 35 criteria total). |
| [`05_validation_plan.md`](05_validation_plan.md) | Automated test execution commands and validation scenarios (`SCEN-001` through `SCEN-032`, 39 scenarios total). |
| [`06_rollout_and_rollback.md`](06_rollout_and_rollback.md) | Phased rollout sequence, blast radius analysis, and migration guide. |
| [`07_traceability.md`](07_traceability.md) | Full bidirectional traceability matrix and closed decisions ledger. |

---

## 6. Implementation Readiness

- **SDD Decision-Complete**: **YES**
- **Architectural Gaps Remaining**: 0
- **Invalid SDK Assumptions**: 0
- **Broken Traceability Links**: 0
- **Unresolved Choices**: None (zero ambiguous alternatives, zero pending architectural questions).
- **Orphaned Requirements / Tasks**: None (100% bidirectional coverage).
- **Productive Code Changes**: None in this planning task. Ready for phase-by-phase implementation.
