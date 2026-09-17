# Task Plan — Controlled Agent Lifecycle Semantics

All tasks are completed.

---

## Phase 1: Foundational Core Contracts & Profile Declarations

- [x] **CAL-TASK-0001**: Declare `controlled_turn` profile specification in `src/proteo_runtime/core/profiles.py`.
  - Add `controlled_turn` to `DEFAULT_PROFILE_SPECS` with `LifecycleMode.EPHEMERAL`, `ContextPolicy.EXTERNAL`, `HostToolsMode.CONTROLLED`, and `SecurityPolicy.CONTROLLED_TOOLS`.
  - Update `ExecutionProfileName` type union.
  - *Maps to*: CAL-REQ-001, CAL-REQ-003.

- [x] **CAL-TASK-0002**: Update `controlled_agent` profile specification to task-scoped runtime context in `src/proteo_runtime/core/profiles.py`.
  - Update `controlled_agent` entry in `DEFAULT_PROFILE_SPECS` to use `ContextPolicy.RUNTIME`.
  - *Maps to*: CAL-REQ-002, CAL-REQ-003.

- [x] **CAL-TASK-0003**: Update `RuntimeConfigV1` validation model in `src/proteo_runtime/config/models.py`.
  - Allow profile configurations combining `LifecycleMode.EPHEMERAL` with `ContextPolicy.RUNTIME`.
  - *Maps to*: CAL-REQ-004.

- [x] **CAL-TASK-0004**: Add default Codex mappings for `controlled_turn` in `src/proteo_runtime/config/defaults/codex_v1.json`.
  - Declare model and reasoning effort mappings for levels `low`, `medium`, `high`, and `ultra`.
  - *Maps to*: CAL-REQ-005, CAL-REQ-006.

- [x] **CAL-TASK-0005**: Implement `RuntimeTask[T]` Protocol contract in `src/proteo_runtime/core/task.py`.
  - Define protocol with `id`, `instructions` (read-only), `ainvoke(input: str | RuntimeInput, ...)`, `astream(input: str | RuntimeInput, ...)`, `interrupt()`, `close()`, and async context manager.
  - Re-export `RuntimeTask` in `src/proteo_runtime/__init__.py`.
  - *Maps to*: CAL-REQ-007, CAL-REQ-008c, CAL-REQ-009, CAL-REQ-010b.

- [x] **CAL-TASK-0006**: Add `task(...)` and `get_task(...)` factory methods to `Runtime` protocol in `src/proteo_runtime/core/runtime.py`.
  - Declare `async def task(...)` signature with `instructions: str | None = None`.
  - Declare `def get_task(self, task_id: str) -> RuntimeTask[Any]`.
  - Preserve synchronous `def model(...) -> RuntimeModel[Any]`.
  - *Maps to*: CAL-REQ-008.

- [x] **CAL-TASK-0007**: Add `ephemeral_tasks: bool = False` to `RuntimeCapabilities` and update supporting provider runtimes.
  - In `src/proteo_runtime/core/capabilities.py`: add `ephemeral_tasks: bool = False` to `RuntimeCapabilities`.
  - In `src/proteo_runtime/providers/codex/runtime.py`: update `CodexRuntime.capabilities()` to advertise `ephemeral_tasks=True` and propagate in `effective_capabilities()`.
  - In `src/proteo_runtime/testing/fakes.py`: update `FakeRuntime` default `_capabilities` to advertise `ephemeral_tasks=True` and propagate in `effective_capabilities()`.
  - Preserve `ephemeral_tasks=False` for any runtime without task-scoped multi-turn context support.
  - *Maps to*: CAL-REQ-020.

- [x] **CAL-TASK-0008**: Add runtime events, result attributes, and `ToolRequest.task_id` correlation.
  - In `src/proteo_runtime/core/events.py`: add `RuntimeEventKind.TASK_STARTED`, `RuntimeEventKind.TASK_CLOSED`, and `task_id: str | None = None` to `RuntimeEvent`.
  - In `src/proteo_runtime/core/model.py`: add `task_id: str | None = None` to `RuntimeResult`.
  - In `src/proteo_runtime/tools/__init__.py`: add `task_id: str | None = None` to `ToolRequest`.
  - In `ToolExecutor` event emission path (currently implemented via `_emit(...)`): ensure the emission path propagates `request.task_id -> RuntimeEvent.task_id` across all emitted tool lifecycle events (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_DENIED`, and retries).
  - *Maps to*: CAL-REQ-021.

---

## Phase 2: Provider Implementation (`CodexRuntime` & `FakeRuntime`)

- [x] **CAL-TASK-0009**: Enforce factory lifecycle boundaries and mandatory tool bindings across `model()`, `task()`, and `session()`.
  - In `CodexRuntime` and `FakeRuntime`, reject synchronous `runtime.model(profile="controlled_agent")` immediately with `CapabilityError`.
  - In `runtime.task(profile="controlled_agent")`, validate mandatory host tool bindings: enforce explicit entry guard `if registry is None: raise CapabilityError("A host-tool registry is required for this profile")` before delegating to `_tool_binding()` (rejecting executor-only calls without registry), support optional `executor` (defaulting to compatible `ToolExecutor(snapshot)` when `None`), reject empty registry with `CapabilityError("A host-tool registry must contain at least one tool")`, and reject mismatched executor with `CapabilityError("Tool executor does not match the registry snapshot")`.
  - Check `capabilities = await self.capabilities()` asynchronously before task creation.
  - *Maps to*: CAL-REQ-008b, CAL-REQ-008e.

- [x] **CAL-TASK-0010**: Implement active in-memory task registry `_tasks` and non-resumability guard in `CodexRuntime` and `FakeRuntime`.
  - Initialize `self._tasks: dict[str, RuntimeTask[Any]] = {}`.
  - Implement `get_task(task_id)` raising `SessionNotFoundError` if missing or closed.
  - Implement non-resumability entry guard in `resume_session()` for both `CodexRuntime` and `FakeRuntime`: if the input descriptor/session_id starts with `task_`, raise `SessionNotFoundError(f"Task '{identifier}' is ephemeral and cannot be resumed as a session")` immediately before calling `SessionCodec.decode()`.
  - Implement cascaded close in `runtime.close()`.
  - *Maps to*: CAL-REQ-008d, CAL-REQ-009.

- [x] **CAL-TASK-0011**: Implement `task(..., instructions=...)` in `FakeRuntime`.
  - Enforce mandatory `registry` and optional `executor` validation matching the six-case tool binding matrix.
  - Return `FakeTask` supporting frozen read-only instructions, tool binding snapshot, multi-turn state simulation, context replay protection, and single-turn concurrency enforcement.
  - *Maps to*: CAL-REQ-008, CAL-REQ-008c, CAL-REQ-008e, CAL-REQ-010b.

- [x] **CAL-TASK-0012**: Implement `task(..., instructions=...)` in `CodexRuntime` with compatibility bridge wire translation.
  - Enforce mandatory `registry` and optional `executor` validation via explicit entry guard `if registry is None: raise CapabilityError(...)`.
  - In `src/proteo_runtime/providers/codex/experimental.py::start_thread()`: translate `developer_instructions -> developerInstructions` in raw request dictionary passed to `_client.thread_start()`, ensuring `baseInstructions` is never replaced or overwritten.
  - In `CodexRuntime.task(...)`: initialize live ephemeral thread via `start_thread(..., developer_instructions=instructions, ephemeral=True)`.
  - Maintain snake_case `developer_instructions` in Python and camelCase `developerInstructions` exclusively on the App Server wire protocol.
  - Return `_CodexTask` instance with read-only `instructions` property.
  - *Maps to*: CAL-REQ-008, CAL-REQ-008c, CAL-REQ-008e, CAL-REQ-008f, CAL-REQ-012.

- [x] **CAL-TASK-0013**: Implement bounded `_StatefulContext` helper and single-active-turn locking.
  - Implement single-turn locking using `asyncio.Lock`, raising `SessionBusyError("Task already has an active turn")` on conflict.
  - *Maps to*: CAL-REQ-010.

- [x] **CAL-TASK-0013b**: Implement hardened context replay protection in `_StatefulContext` / `RuntimeTask`.
  - Validate that `input: str | RuntimeInput` contains only `user` role messages.
  - Clarify that `RuntimeMessage` strictly admits `Literal["system", "user", "assistant", "tool"]`; `developer` is not a message role (developer instructions exist exclusively via `runtime.task(instructions=...)`).
  - Reject `RuntimeMessage` instances with role `system`, `assistant`, or `tool` with `ContextPolicyError("Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; replaying 'assistant', 'tool', or injecting 'system' messages is prohibited.")`.
  - *Maps to*: CAL-REQ-010b.

- [x] **CAL-TASK-0014**: Implement task workspace directory lifecycle.
  - Create isolated temporary directory on task start, share across turns, delete on task close.
  - *Maps to*: CAL-REQ-013.

- [x] **CAL-TASK-0015**: Implement explicit lifecycle state machine (`OPEN -> CLOSING -> CLOSED`) and idempotent `RuntimeTask.close()` teardown.
  - Implement three-state lifecycle: `OPEN`, `CLOSING`, `CLOSED`.
  - In `ainvoke()`, `astream()`, and `interrupt()`, reject calls immediately with `SessionNotFoundError("Task '{task_id}' not found or already closed")` if state is `CLOSING` or `CLOSED`, preventing turns from starting while cleanup is underway.
  - In `close()`, transition immediately from `OPEN` to `CLOSING`; ensure concurrent `close()` calls do not duplicate cleanup or emit duplicate `TASK_CLOSED` events.
  - Execute teardown sequence: cancel active turn directly via internal cancellation primitive (e.g. `await active_run.interrupt()`, without calling public `task.interrupt()`), wait bounded cancellation grace period, unregister mux routes, `ToolExecutor.end_invocation(active_invocation_id)`, provider thread release, workspace cleanup, and registry removal.
  - Handle cleanup step failures with diagnostic logging, keeping task handle closed.
  - *Maps to*: CAL-REQ-011, CAL-REQ-011b, CAL-REQ-014, CAL-REQ-014b.

---

## Phase 3: Semantic Configuration Freezing & Tool Execution

- [x] **CAL-TASK-0016**: Freeze semantic configuration and tool authority at task creation.
  - Capture immutable snapshot of profile, model, reasoning effort, security policy, instructions, tool registry snapshot, executor, and workspace.
  - *Maps to*: CAL-REQ-015.

- [x] **CAL-TASK-0017**: Implement per-turn `InvocationConfig` validation.
  - Allow `timeout_seconds`, `include_raw`, and `metadata`.
  - Reject attempts to modify `model` or `reasoning_effort` with `ConfigurationError` before inference.
  - Note that `InvocationConfig` declares no `instructions` field.
  - *Maps to*: CAL-REQ-008c, CAL-REQ-015b.

- [x] **CAL-TASK-0018**: Enforce per-turn `invocation_id` routing, `ToolRequest` correlation, and `ToolExecutor.end_invocation(invocation_id)` cleanup.
  - Generate fresh `invocation_id` / `turn_id` for every turn in `_CodexTask`.
  - In `CodexToolBridge` (`src/proteo_runtime/providers/codex/experimental.py`), populate `ToolRequest` with `task_id=task.id`, `invocation_id=turn.invocation_id`, `turn_id=turn.turn_id`, and `session_id=None`.
  - Invoke `ToolExecutor.end_invocation(invocation_id)` (`src/proteo_runtime/tools/__init__.py`) at the conclusion of every turn.
  - *Maps to*: CAL-REQ-016, CAL-REQ-017.

- [x] **CAL-TASK-0019**: Bind dynamic tools into Codex SDK mux for task turns and route requests safely.
  - Register tool handlers in `CodexToolMux` routes (`src/proteo_runtime/providers/codex/experimental.py`) matching active thread and turn for the duration of each turn.
  - Dispatch incoming provider tool calls to `CodexToolBridge` (`src/proteo_runtime/providers/codex/experimental.py`) with stable `task_id` and turn identifiers.
  - Ensure tool requests for unknown multiplexer routes fail closed without tool execution or state leakage.
  - Unregister routes on turn completion, error, or cancellation.
  - *Maps to*: CAL-REQ-018.

---

## Phase 4: Integrations & Observability

- [x] **CAL-TASK-0020**: Implement `RuntimeNode` task routing and mutual exclusion.
  - Support `proteo_task_id` in `RunnableConfig["configurable"]`.
  - Resolve active task via `runtime.get_task(task_id)`.
  - Raise `ConfigurationError` if both `proteo_task_id` and `proteo_session_id` are passed.
  - *Maps to*: CAL-REQ-008d, CAL-REQ-019.

- [x] **CAL-TASK-0021**: Propagate `task_id` to OpenTelemetry spans, LangSmith metadata, and turn events.
  - Attach `proteo.task_id` to OTel spans.
  - Project `metadata["proteo_task_id"]` to LangSmith.
  - Ensure raw provider thread IDs are never leaked.
  - *Maps to*: CAL-REQ-021.

---

## Phase 5: Testing, Validation & Examples Migration

- [x] **CAL-TASK-0022**: Migrate Smart Quote Agent example to `profile="controlled_turn"`.
  - Update `examples/smart_quote_agent/app.py` (Line 159), `graph.py`, `README.md`, and `tests/test_agent.py` to use `controlled_turn`.
  - *Maps to*: CAL-REQ-022.

- [x] **CAL-TASK-0023**: Unit tests for profile resolution, capabilities, and factory boundaries.
  - Add comprehensive unit tests in `tests/unit/core/test_controlled_profiles.py`.
  - Test factory boundary rejections and prescriptive error messages without `await` on `runtime.model(...)`.
  - *Maps to*: CAL-REQ-006, CAL-REQ-008b, CAL-REQ-020, CAL-REQ-023.

- [x] **CAL-TASK-0024**: Unit tests for task lifecycle, tool binding validation, instructions, concurrency, user-only replay protection, non-resumability, tool mux execution, and idempotent close.
  - Add comprehensive unit tests in `tests/unit/tools/test_controlled_agent.py`.
  - Test task creation with valid tool bindings, fail-fast on missing/empty/mismatched bindings, instructions persistence, read-only property, prohibited config override rejection, single-turn concurrency lock (`SessionBusyError`), user-only context replay protection (`ContextPolicyError`), non-resumability entry guard in `resume_session()` for active and closed tasks raising `SessionNotFoundError` before reaching `SessionCodec` without affecting non-task descriptors, race prevention during teardown (calling `ainvoke()`/`astream()` during `CLOSING` state immediately raises `SessionNotFoundError` before inference), concurrent `close()` idempotency emitting `TASK_CLOSED` exactly once, post-close invalidation (`SessionNotFoundError`), tool multiplexer routing and fail-closed behavior for unknown routes, propagation of `task_id` from `ToolRequest` to all emitted tool events, and task registry cleanup.
  - *Maps to*: CAL-REQ-008c, CAL-REQ-008d, CAL-REQ-008e, CAL-REQ-009, CAL-REQ-010, CAL-REQ-010b, CAL-REQ-011, CAL-REQ-011b, CAL-REQ-014b, CAL-REQ-015b, CAL-REQ-018, CAL-REQ-023.

- [x] **CAL-TASK-0025**: Live Codex multi-turn smoke test with subscription authentication.
  - Implement opt-in integration test in `tests/integration/codex/test_codex_controlled_agent.py`.
  - Use Codex-managed subscription authentication via Codex App Server / CLI login (`codex login`).
  - Pre-flight check executes `await runtime.start()`, skipping gracefully via `pytest.skip` if `AuthenticationError` occurs.
  - Verify multi-turn memory reuse and clean context on second task with tool execution without requiring `OPENAI_API_KEY`.
  - *Maps to*: CAL-REQ-024.

---

## Phase 6: Documentation & Governance

- [x] **CAL-TASK-0026**: Validate and synchronize ADR 0004.
  - Review `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md` against final SDD decisions and ensure perfect synchronization.
  - *Maps to*: CAL-REQ-026.

- [x] **CAL-TASK-0027**: Synchronize Design Guide.
  - Verify `docs/design/project-guide.md` sections match implemented semantics.
  - *Maps to*: CAL-REQ-025.
