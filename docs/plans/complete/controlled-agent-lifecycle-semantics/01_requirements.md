# Requirements — Controlled Agent Lifecycle Semantics

## Functional Requirements

### 1. Profile Semantics

#### CAL-REQ-001 — Built-in Profile: `controlled_turn`
The runtime must provide a built-in execution profile named `controlled_turn`.
- **Lifecycle**: `LifecycleMode.EPHEMERAL` (invocation-scoped).
- **Context Policy**: `ContextPolicy.EXTERNAL` (host provides all relevant conversational context).
- **Host Tools Mode**: `HostToolsMode.CONTROLLED` (host provides tools from an explicit registry).
- **Security Policy**: `SecurityPolicy.CONTROLLED_TOOLS` (host executes tools; native tools denied).
- **Behavior**: Starts from a clean runtime context on every host invocation; no provider history is reused across calls.

#### CAL-REQ-002 — Built-in Profile: `controlled_agent` Re-definition
The runtime must update the built-in profile `controlled_agent` to task-scoped stateful ephemeral semantics.
- **Lifecycle**: `LifecycleMode.EPHEMERAL` (task-scoped; context is discarded when the task ends).
- **Context Policy**: `ContextPolicy.RUNTIME` (Proteo owns task-local conversational history).
- **Host Tools Mode**: `HostToolsMode.CONTROLLED` (explicit registry only).
- **Security Policy**: `SecurityPolicy.CONTROLLED_TOOLS` (fail-closed host execution).
- **Behavior**: The same runtime/provider task context is reused across all turns within the active task. When the task closes, its context is destroyed. It is non-durable and non-resumable.

#### CAL-REQ-003 — Default Profile Specifications Matrix
`DEFAULT_PROFILE_SPECS` in `src/proteo_runtime/core/profiles.py` must include both `controlled_turn` and `controlled_agent` with their exact respective specifications. `profile_spec()` must successfully resolve both profiles.

#### CAL-REQ-004 — Configuration Schema Compatibility
The Pydantic configuration model `RuntimeConfigV1` in `src/proteo_runtime/config/models.py` must validate and permit profiles configured with `LifecycleMode.EPHEMERAL` and `ContextPolicy.RUNTIME`. Custom profile specifications must not be rejected merely because an ephemeral lifecycle has runtime context ownership.

---

### 2. Configuration & Model Resolution

#### CAL-REQ-005 — Default Codex Mappings for `controlled_turn`
The default packaged configuration file `src/proteo_runtime/config/defaults/codex_v1.json` must declare an explicit profile entry for `controlled_turn` containing valid model and reasoning effort mappings across all four logical levels: `low`, `medium`, `high`, and `ultra`.

#### CAL-REQ-006 — Strict Profile Lookup Without Fallback
`RuntimeConfigV1.lookup(profile, level)` and runtime model factories must resolve `controlled_turn` and `controlled_agent` as distinct, independent profile keys. The configuration subsystem must never silently fall back or alias from one profile name to another.

---

### 3. Public Task Lifecycle (`RuntimeTask`) & Factory Boundaries

#### CAL-REQ-007 — `RuntimeTask[T]` Protocol Contract
The core package must expose a provider-neutral asynchronous protocol `RuntimeTask[T]` in `src/proteo_runtime/core/task.py` (and re-exported from `proteo_runtime`), providing:
- `id: str`: A Proteo-generated, provider-neutral, task-scoped identifier (`f"task_{uuid.uuid4().hex}"`).
- `instructions: str | None`: Read-only property returning the initial task-scoped instructions frozen at task creation.
- `async def ainvoke(input: str | RuntimeInput, *, config=None, include_raw=None) -> RuntimeResult[T]`: Executes one turn within the task.
- `def astream(input: str | RuntimeInput, *, config=None, include_raw=None) -> AsyncIterator[RuntimeEvent]`: Streams events for one turn.
- `async def interrupt() -> None`: Interrupts the currently active turn.
- `async def close() -> None`: Discards runtime context, releases/destroys provider resources, and marks the task closed.
- `async def __aenter__() -> RuntimeTask[T]` and `async def __aexit__(exc_type, exc_val, exc_tb) -> None`: Async context manager support.

#### CAL-REQ-008 — `Runtime.task(...)` Factory Method
The `Runtime` protocol in `src/proteo_runtime/core/runtime.py` and its concrete implementations (`CodexRuntime`, `FakeRuntime`) must provide an asynchronous factory method:
```python
async def task(
    self,
    profile: str = "controlled_agent",
    *,
    level: str = "medium",
    instructions: str | None = None,
    config: InvocationConfig | None = None,
    registry: ToolRegistry | None = None,
    executor: ToolExecutor | None = None,
) -> RuntimeTask[Any]: ...
```
Calling `task()` must validate that:
1. The requested profile has `LifecycleMode.EPHEMERAL` and `ContextPolicy.RUNTIME`.
2. The runtime supports `RuntimeCapabilities.ephemeral_tasks == True` (checked asynchronously via `await self.capabilities()`).
3. Required tool bindings are present and valid for controlled tool profiles.

#### CAL-REQ-008b — Factory Method Lifecycle Boundary Enforcement
Every factory method on `Runtime` must strictly enforce matching profile lifecycle and context policies at factory call time:
1. `Runtime.model(profile=...)` is synchronous and restricted exclusively to profiles with `ContextPolicy.EXTERNAL` and `LifecycleMode.EPHEMERAL` (`brain`, `structured`, `controlled_turn`).
   - Calling `runtime.model(profile="controlled_agent")` MUST fail immediately with `CapabilityError`.
   - Error message: `"Profile 'controlled_agent' has runtime context and requires an explicit task lifecycle via runtime.task(); use 'controlled_turn' for invocation-scoped model execution."`
   - Calling `runtime.model()` with persistent profiles (`session`) or explicit profiles (`native`) MUST raise `CapabilityError`.
2. `Runtime.task(profile=...)` is asynchronous and restricted exclusively to profiles with `ContextPolicy.RUNTIME` and `LifecycleMode.EPHEMERAL` (`controlled_agent`).
   - Calling `runtime.task(profile="controlled_turn")`, `runtime.task(profile="brain")`, or `runtime.task(profile="structured")` MUST fail immediately with `CapabilityError("Profile '...' has external context; use runtime.model() for invocation-scoped execution")`.
   - Calling `runtime.task(profile="session")` MUST fail immediately with `CapabilityError("Profile 'session' is persistent; use runtime.session() for durable sessions")`.
3. `Runtime.session(profile=...)` is asynchronous and restricted exclusively to profiles with `LifecycleMode.PERSISTENT` and `ContextPolicy.RUNTIME` or `ContextPolicy.HYBRID` (`session`).
   - Calling `runtime.session(profile="controlled_agent")` MUST fail immediately with `CapabilityError("Profile 'controlled_agent' is ephemeral; use runtime.task() for ephemeral task execution")`.
   - Calling `runtime.session(profile="controlled_turn")` MUST fail immediately with `CapabilityError("Profile 'controlled_turn' is ephemeral and external; use runtime.model() for invocation-scoped execution")`.
Silent degradation, fallback, or hidden sticky context across factory methods is strictly forbidden.

#### CAL-REQ-008c — Task-Scoped Instructions & Provider Mapping
Initial agent instructions (system prompt / task objective) must be accepted exclusively at task creation via `runtime.task(instructions=...)`:
- Instructions are provided exclusively when creating the `RuntimeTask`.
- Instructions remain frozen for the entire lifetime of the task and apply to all turns.
- Callers must NOT resend instructions on subsequent turns.
- Instructions do not form part of the host-managed conversational history or host business state.
- `RuntimeTask` exposes `instructions: str | None` as a read-only property.
- For Codex provider execution, instructions map to provider developer-level instructions (`developer_instructions` in Python).
- No per-turn API exists to modify or replace instructions. `InvocationConfig` intentionally does not declare an `instructions` field, precluding per-turn mutation.
- Instructions are provider-neutral and respect runtime redaction and observability policies.

#### CAL-REQ-008d — Active Runtime Task Registry & Resolution
The runtime implementation (`CodexRuntime`, `FakeRuntime`) must own an active in-memory task registry (`runtime._tasks: dict[str, RuntimeTask[Any]]`):
- `task_id` is generated by Proteo at task creation (`f"task_{uuid.uuid4().hex}"`).
- `task_id` is unique per runtime instance, opaque to callers, and never contains raw provider thread IDs.
- The runtime exposes in-memory resolution `runtime.get_task(task_id: str) -> RuntimeTask[Any]`.
- Calling `task.close()` unregisters the task from `_tasks`.
- Calling `runtime.close()` cascades `close()` to all currently active tasks in `_tasks`.
- Looking up an unknown or already closed `task_id` raises `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
- Active tasks do not survive runtime or process restart; subsequent lookups raise `SessionNotFoundError`.
- In workflow integrations (such as LangGraph), specifying both `proteo_task_id` and `proteo_session_id` in `RunnableConfig` raises `ConfigurationError`.

#### CAL-REQ-008e — Mandatory Host Tool Bindings for `controlled_agent`
Creating a `controlled_agent` task strictly requires a host tool `registry`. The `executor` parameter is optional:
- `registry` is mandatory; `executor` is optional.
- `Runtime.task()` must perform an explicit entry guard before delegating to `_tool_binding()`:
  ```python
  if registry is None:
      raise CapabilityError("A host-tool registry is required for this profile")
  ```
  This prevents creating a `controlled_agent` task with only an `executor` (`registry=None, executor=<ToolExecutor>`).
- If `executor` is omitted (`executor=None`), the runtime constructs a default `ToolExecutor` compatible with `registry.snapshot()`.
- If `registry` is empty (`not snapshot.definitions()`), `runtime.task()` must fail fast with `CapabilityError("A host-tool registry must contain at least one tool")`.
- If `executor` is provided and its snapshot does not match the registry snapshot, `runtime.task()` must fail fast with `CapabilityError("Tool executor does not match the registry snapshot")`.
- Exact case outcomes:
  - `registry=None, executor=None` -> Raises `CapabilityError("A host-tool registry is required for this profile")`.
  - `registry=None, executor=executor` -> Raises `CapabilityError("A host-tool registry is required for this profile")`.
  - `registry=empty_registry, executor=...` -> Raises `CapabilityError("A host-tool registry must contain at least one tool")`.
  - `registry=valid_registry, executor=None` -> **Valid**; runtime builds compatible executor.
  - `registry=valid_registry, executor=matching_executor` -> **Valid**.
  - `registry=valid_registry, executor=mismatched_executor` -> Raises `CapabilityError("Tool executor does not match the registry snapshot")`.

#### CAL-REQ-008f — Codex Task Instructions Wire Protocol Translation
The private Codex compatibility bridge (`src/proteo_runtime/providers/codex/experimental.py::start_thread()`) must translate Python developer instructions to the raw App Server wire protocol:
- Python caller API in `CodexRuntime.task(...)` invokes `start_thread(..., developer_instructions=instructions)`.
- The bridge translates `developer_instructions` into camelCase `developerInstructions` in the raw dictionary passed to `_client.thread_start(raw)`.
- The key `developer_instructions` is removed from `raw` after translation to ensure no duplicate or malformed fields are sent.
- Provider base instructions (`baseInstructions`) must remain completely intact and must never be replaced, cleared, or overwritten.
- Core Proteo contracts, `RuntimeTask`, and public APIs remain provider-neutral, using snake_case exclusively and never exposing or passing camelCase `developerInstructions` directly.

#### CAL-REQ-009 — Non-Resumability Guard & SessionCodec Protection
A `task_id` generated by Proteo conforms to the reserved namespace format `task_<opaque-id>`:
- **No SessionDescriptor**: A `task_id` is not a `SessionDescriptor` and must never be passed to or processed by `SessionCodec`.
- **Explicit Non-Resumability Guard**: When `await runtime.resume_session(session_id)` (or `descriptor`) is invoked with any identifier starting with the reserved `task_` prefix, the runtime (`CodexRuntime`, `FakeRuntime`) must fail fast **before** reaching `SessionCodec.decode()` by raising:
  ```python
  SessionNotFoundError(f"Task '{session_id}' is ephemeral and cannot be resumed as a session")
  ```
- **Lifecycle Semantics Failure**: This guard guarantees that attempts to resume ephemeral tasks fail with `SessionNotFoundError` reflecting lifecycle semantics, rather than being rejected inside `SessionCodec.decode()` with syntax errors or `SessionMismatchError`.
- **Handle Boundaries**: A `RuntimeTask` must not produce or expose a `SessionDescriptor`, and must not implement `archive()` or `delete()` methods.

#### CAL-REQ-010 — Single-Active-Turn Concurrency Enforcement
Only one turn may execute at any given time within an active `RuntimeTask`. If `ainvoke()` or `astream()` is called while another turn is currently running on the same task instance, the call must fail immediately with `SessionBusyError("Task already has an active turn")`.

#### CAL-REQ-010b — Hardened Context Replay Protection (User-Only Input)
`RuntimeTask.ainvoke()` and `astream()` accept `input: str | RuntimeInput`:
- A plain `str` input is treated as a single message with role `user`.
- For execution under `ContextPolicy.RUNTIME`, the caller may ONLY provide new `user` message input for the current turn.
- The provider-neutral `RuntimeMessage` contract strictly declares `role: Literal["system", "user", "assistant", "tool"]`. The identifier `developer` is NOT a `RuntimeMessage` role and cannot be passed as a message.
- Any `RuntimeInput` containing messages with non-`user` roles (`system`, `assistant`, or `tool`) must be rejected before inference with:
  ```python
  ContextPolicyError(
      "Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; "
      "replaying 'assistant', 'tool', or injecting 'system' messages is prohibited."
  )
  ```
- Manual replay of conversation history already owned by the runtime is strictly prohibited.
- Per-turn developer or system instructions are strictly prohibited; developer instructions exist exclusively as task-scoped instructions configured at task initialization via `runtime.task(instructions=...)`.
- The host owns business/workflow state, not the technical conversation transcript of the task.

#### CAL-REQ-011 — Post-Close Invalidation
Once a `RuntimeTask` transitions to `CLOSED`, subsequent calls to `ainvoke()`, `astream()`, or `interrupt()` on that handle must fail immediately with `SessionNotFoundError("Task '{task_id}' not found or already closed")`. Task state must not linger in an operable condition.

#### CAL-REQ-011b — Task State Machine & Teardown Race Prevention (OPEN -> CLOSING -> CLOSED)
A `RuntimeTask` must enforce an explicit three-state lifecycle: `OPEN -> CLOSING -> CLOSED`:
- **Immediate Invalidation upon `CLOSING`**: The instant `task.close()` begins teardown, the state transitions from `OPEN` to `CLOSING`. From that exact moment, the task ceases to accept new turns.
- **Fail-Fast Rejection of New Turns & Public Calls**: Any call to `ainvoke()`, `astream()`, or `interrupt()` that attempts to begin after the task enters `CLOSING` must fail immediately before initiating provider inference, tool execution, or resource allocation, raising:
  ```python
  SessionNotFoundError(f"Task '{task_id}' not found or already closed")
  ```
  This guarantees that new turns cannot start while tool routes, provider contexts, workspaces, or active task registry entries are being dismantled.
- **Separation of Public Interrupt and Internal Cancellation**: The public `RuntimeTask.interrupt()` method strictly obeys lifecycle state guards and is rejected during `CLOSING` and `CLOSED`. `task.close()` owns the teardown workflow and cancels any currently active turn directly through the internal provider/run cancellation primitive (e.g. `await active_run.interrupt()`) without invoking the public `task.interrupt()` method.
- **Concurrent `close()` Idempotency**: If `close()` is called concurrently while the task is already in `CLOSING` or `CLOSED`, exactly one execution performs the teardown sequence; concurrent calls safely await completion or return `None` without duplicating cleanup steps and ensuring `TASK_CLOSED` is emitted strictly once.

---

### 4. Codex Provider Implementation

#### CAL-REQ-012 — Ephemeral Thread Reuse in `CodexRuntime`
When a `controlled_agent` task is created, `CodexRuntime` must initialize exactly one provider thread with `ephemeral=True` via the pinned Codex SDK client (`thread_start(ephemeral=True)` / `start_thread(..., ephemeral=True)`). Subsequent turns within the same task must invoke `thread.turn(...)` against that identical live provider thread.

#### CAL-REQ-013 — Task Workspace Lifecycle
`CodexRuntime` must create an isolated temporary workspace directory upon task creation. All turns in that task must share that workspace directory. The workspace must remain intact across turns and be completely removed when the task closes.

#### CAL-REQ-014 — Task Teardown and Cleanup Sequence
When `RuntimeTask.close()` is invoked on a task, the runtime must execute the following exact sequence:
1. Mark task closing (`self._state = TaskState.CLOSING`).
2. If a turn is active: request turn cancellation directly via the internal provider/run cancellation primitive (e.g. `await active_run.interrupt()`; `close()` does not invoke the public `RuntimeTask.interrupt()` method, avoiding self-conflict with the `CLOSING` state guard) and wait a bounded cancellation grace period (default 5.0 seconds).
3. Invalidate provider context if cleanup confirmation cannot be achieved.
4. Unregister tool bridge and dynamic multiplexer routes.
5. Invoke `ToolExecutor.end_invocation(active_invocation_id)` for any active turn.
6. Release/destroy provider task context where supported (Codex SDK ephemeral thread).
7. Remove temporary workspace directory from filesystem.
8. Remove task from the runtime active registry (`runtime._tasks`).
9. Mark handle closed (`self._state = TaskState.CLOSED`).
10. Emit `TASK_CLOSED` runtime event.

#### CAL-REQ-014b — Idempotent `close()` and Teardown Resilience
`RuntimeTask.close()` must be strictly idempotent:
- The first invocation executes teardown and cleanup.
- A second or subsequent call is a safe no-op that returns `None` without raising an error.
- If a cleanup step fails (e.g., filesystem deletion error or network failure during provider thread release), the teardown continues best-effort with remaining steps, logs an observability diagnostic failure, leaves the task in an unusable/closed state, and does not reopen the task.
- `TASK_CLOSED` is emitted exactly once.

---

### 5. Tool Bindings & Semantic Authority Freezing

#### CAL-REQ-015 — Freezing Semantic Configuration & Authority at Task Creation
At the moment of task creation, the runtime must capture and freeze: profile, resolved model, reasoning effort, context policy, security policy, task instructions, tool registry snapshot, tool executor, permission policy, approval handler, and sandbox workspace policy. The task must not permit dynamic tool schema mutation or permission expansion while active.

#### CAL-REQ-015b — Per-Turn `InvocationConfig` Validation
`RuntimeTask.ainvoke()` and `astream()` accept an optional `InvocationConfig` per turn:
- **Allowed Per-Turn Overrides**: `timeout_seconds`, `include_raw`, and `metadata`.
- **Prohibited Per-Turn Overrides**: `model` (if different from frozen model) and `reasoning_effort` (if different from frozen effort).
- Attempting to modify any prohibited field raises `ConfigurationError` before inference begins. Overrides are never silently ignored.

#### CAL-REQ-016 — Identifier Semantics & ToolRequest Correlation
Every turn executed within a `RuntimeTask` maintains a strict distinction across identifier concepts:
- `task_id`: Stable throughout the entire `RuntimeTask` lifecycle, correlating all turns and events.
- `turn_id`: Identifies an individual conversational turn within the task.
- `invocation_id`: Identifies a specific provider/tool execution attempt within that turn, serving as the unique key used by `ToolExecutor` for execution deduplication and cleanup.

Every turn executed within a `RuntimeTask` must generate a distinct, unique `invocation_id` and `turn_id`.
The dynamic tools bridge (`CodexToolBridge` in `src/proteo_runtime/providers/codex/experimental.py`) must construct `ToolRequest` with:
- `task_id`: Populated with the stable `RuntimeTask.id`.
- `invocation_id`: Populated with that specific turn's unique invocation ID.
- `turn_id`: Populated with that specific turn's unique turn ID.
- `session_id`: Strictly `None` (raw provider thread IDs are never assigned to `session_id` or `task_id`).
Conversely, for persistent sessions (`RuntimeSession`), `ToolRequest.task_id` remains `None` while `ToolRequest.session_id` carries the session identity.

#### CAL-REQ-017 — ToolExecutor Per-Turn Lifecycle Hook (`ToolExecutor.end_invocation`)
`ToolExecutor.end_invocation()` contractually and exclusively takes `invocation_id` as its argument, as `invocation_id` is the key used by `ToolExecutor` to track, deduplicate, and clean up tool execution state. `turn_id` must never be passed to `end_invocation()`.

`CodexRuntime` must call `ToolExecutor.end_invocation(invocation_id)` at the completion or failure of every individual turn within a task, ensuring per-turn tool execution state is finalized promptly.
If a turn is currently active during task teardown (`RuntimeTask.close()`), the runtime must call `ToolExecutor.end_invocation(active_invocation_id)` for that active turn.

#### CAL-REQ-018 — Live Tool Execution via Mux Registration & Routing
Turns in a `controlled_agent` task must dynamically bind host tools into the Codex SDK multiplexer routes for the duration of the turn and execute them safely with full policy enforcement:
- `CodexToolMux` (in `src/proteo_runtime/providers/codex/experimental.py`) routes provider tool calls matching the active thread and turn to the registered `CodexToolBridge`.
- `CodexToolBridge` builds `ToolRequest` with stable `task_id`, turn-specific `invocation_id` and `turn_id`, and `session_id=None`.
- `ToolExecutor` (in `src/proteo_runtime/tools/__init__.py`) executes the tool and returns the response to the provider.
- All tool lifecycle events emitted during execution (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_DENIED`, retries) must include `task_id` copied from `ToolRequest.task_id`.
- Tool calls arriving on unknown or unregistered multiplexer routes must fail closed without invoking tools or leaking internal state.

---

### 6. Integrations & Frameworks

#### CAL-REQ-019 — LangGraph `RuntimeNode` Ephemeral Task Routing
`RuntimeNode` in `src/proteo_runtime/integrations/langgraph/node.py` must support executing ephemeral tasks via `proteo_task_id` in `RunnableConfig["configurable"]`:
- If `proteo_task_id` is supplied, `RuntimeNode` resolves the active task from `runtime.get_task(task_id)` and invokes `ainvoke()`.
- If both `proteo_task_id` and `proteo_session_id` are passed, `RuntimeNode` raises `ConfigurationError("Cannot specify both proteo_task_id and proteo_session_id in RunnableConfig")`.
- If `proteo_task_id` is unknown or already closed, `SessionNotFoundError` is raised.

---

### 7. Runtime Capabilities & Feature Flags

#### CAL-REQ-020 — Distinct Ephemeral Task Capability (`ephemeral_tasks`)
The `RuntimeCapabilities` model in `src/proteo_runtime/core/capabilities.py` must declare an explicit, independent boolean flag:
```python
ephemeral_tasks: bool = False
```
Capability declaration and advertising rules:
- `ephemeral_sessions: bool`: Indicates support for one-shot ephemeral thread/invocation execution (`brain`, `structured`, `controlled_turn`).
- `ephemeral_tasks: bool`: Indicates support for multi-turn ephemeral task execution with runtime-owned context reuse (`controlled_agent`).
- `persistent_sessions: bool`: Indicates support for durable, resumable multi-turn sessions (`session`).

Provider advertising requirements:
- `CodexRuntime.capabilities()` must advertise `ephemeral_tasks=True` when the runtime can support `RuntimeTask` and required provider capabilities are available.
- `FakeRuntime.capabilities()` must advertise `ephemeral_tasks=True` by default, enabling full `RuntimeTask` simulation in test suites.
- Any runtime that does not implement task-scoped multi-turn context (or when explicitly configured without it) must maintain `ephemeral_tasks=False`.

Execution profile enforcement:
- `controlled_agent` requires `host_tools=True` and `ephemeral_tasks=True`. Invoking `runtime.task(profile="controlled_agent", ...)` on any runtime with `ephemeral_tasks=False` must fail fast with `CapabilityError(f"Runtime '{self.name}' does not support ephemeral multi-turn tasks.")` before initiating any provider thread or allocating task handles.
- `controlled_turn` requires `host_tools=True` and `ephemeral_sessions=True`, but does NOT require `ephemeral_tasks`.

---

### 8. Observability & Telemetry

#### CAL-REQ-021 — Complete Observability & Correlation Propagation
`RuntimeResult`, `RuntimeEvent`, `ToolRequest`, OpenTelemetry spans, and LangSmith metadata must correlate multi-turn task execution:
- `RuntimeEvent.task_id`, `TASK_STARTED`, and `TASK_CLOSED` runtime events are declared in `src/proteo_runtime/core/events.py`.
- `ToolRequest.task_id: str | None = None` is declared in `src/proteo_runtime/tools/__init__.py`.
- The `ToolExecutor` event emission path must propagate `request.task_id -> RuntimeEvent.task_id` across all emitted tool events (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_DENIED`, and retry events).
- `RuntimeResult.task_id: str | None = None` is declared in `src/proteo_runtime/core/model.py`.
- `task_id: str`: Set to the stable task identifier across all turns and tool executions.
- `session_id: None`: Remains `None` for tasks and task tool executions, avoiding conflation with durable sessions.
- `turn_id` / `invocation_id`: Unique per turn.
- OpenTelemetry span attributes include `proteo.task_id`. Low-cardinality metric labels must NOT include `task_id`.
- LangSmith metadata includes `proteo_task_id`.
- Raw provider thread IDs are never exposed in public events or attributes.

---

### 9. Examples & Application Migration

#### CAL-REQ-022 — Smart Quote Agent Migration to `controlled_turn`
The Smart Quote Agent example in `examples/smart_quote_agent/` (specifically `app.py`, `graph.py`, `README.md`, and its test suite in `tests/test_agent.py`) must be migrated to use `profile="controlled_turn"` since it performs invocation-scoped single-turn reasoning with external context.

---

### 10. Testing & Verification

#### CAL-REQ-023 — Comprehensive Unit & Integration Test Suite
The test suite must provide comprehensive automated verification of all profiles, factory boundaries, tool binding validations, task lifecycles, and error conditions in `tests/unit/core/test_controlled_profiles.py` and `tests/unit/tools/test_controlled_agent.py`.

#### CAL-REQ-024 — Live Codex Multi-Turn Smoke Test
An integration test in `tests/integration/codex/test_codex_controlled_agent.py` must verify real multi-turn conversation reuse against the live Codex App Server:
- Opt-in via `PROTEO_CODEX_INTEGRATION=1` and `-m integration`.
- Uses subscription-backed Codex authentication via Codex App Server / CLI login (`codex login`).
- Pre-flight check executes `await runtime.start()`. If missing authentication, `start()` raises `AuthenticationError`, which the test catches and skips gracefully via `pytest.skip("Codex subscription login is not active; skipping live integration tests.")`.
- Does NOT require or use `OPENAI_API_KEY`. No invented SDK APIs.

---

### 11. Documentation & Governance

#### CAL-REQ-025 — Design Guide Synchronization
`docs/design/project-guide.md` must be synchronized to document `controlled_turn`, `controlled_agent`, `RuntimeTask`, and factory boundary enforcement.

#### CAL-REQ-026 — Validate and Synchronize ADR 0004
The existing ADR `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md` must be validated and synchronized against the final decision-complete SDD package.
