# Acceptance Criteria — Controlled Agent Lifecycle Semantics

All acceptance criteria are binary, deterministic, and testable.

---

### AC-CAL-001: `controlled_turn` Profile Specification
- **Given** `src/proteo_runtime/core/profiles.py` is loaded,
- **When** `DEFAULT_PROFILE_SPECS["controlled_turn"]` is inspected,
- **Then** `spec.lifecycle` is `LifecycleMode.EPHEMERAL`, `spec.context` is `ContextPolicy.EXTERNAL`, `spec.host_tools` is `HostToolsMode.CONTROLLED`, and `spec.security` is `SecurityPolicy.CONTROLLED_TOOLS`.

### AC-CAL-002: `controlled_agent` Profile Specification
- **Given** `src/proteo_runtime/core/profiles.py` is loaded,
- **When** `DEFAULT_PROFILE_SPECS["controlled_agent"]` is inspected,
- **Then** `spec.lifecycle` is `LifecycleMode.EPHEMERAL`, `spec.context` is `ContextPolicy.RUNTIME`, `spec.host_tools` is `HostToolsMode.CONTROLLED`, and `spec.security` is `SecurityPolicy.CONTROLLED_TOOLS`.

### AC-CAL-003: Profile Resolution
- **Given** `profile_spec` function in `profiles.py`,
- **When** called with `"controlled_turn"` or `"controlled_agent"`,
- **Then** both profiles resolve without raising `ConfigurationError`.

### AC-CAL-004: Configuration Model Compatibility
- **Given** `RuntimeConfigV1` in `src/proteo_runtime/config/models.py`,
- **When** validating a configuration where an ephemeral profile has `ContextPolicy.RUNTIME`,
- **Then** validation succeeds without error.

### AC-CAL-005: Default Codex Mappings for `controlled_turn`
- **Given** `src/proteo_runtime/config/defaults/codex_v1.json`,
- **When** the `profiles` dictionary is inspected,
- **Then** an entry for `"controlled_turn"` exists and maps valid models and reasoning efforts for `low`, `medium`, `high`, and `ultra`.

### AC-CAL-006: Strict Profile Lookup
- **Given** a loaded `RuntimeConfigV1`,
- **When** `config.lookup("controlled_turn", level)` is called,
- **Then** it returns the mapping explicitly configured for `controlled_turn` and does not fall back or alias to `controlled_agent`.

### AC-CAL-007: `RuntimeTask[T]` Protocol Contract
- **Given** `src/proteo_runtime/core/task.py`,
- **When** `RuntimeTask` is inspected,
- **Then** it declares `id: str`, `instructions: str | None` (read-only), `ainvoke(input: str | RuntimeInput, ...)`, `astream(input: str | RuntimeInput, ...)`, `interrupt()`, `close()`, `__aenter__`, and `__aexit__`.

### AC-CAL-008: `Runtime.task(...)` Factory Creation with Tool Bindings
- **Given** an initialized runtime (`CodexRuntime` or `FakeRuntime`), a valid `ToolRegistry` with at least one tool, and matching `ToolExecutor`,
- **When** `await runtime.task(profile="controlled_agent", level="medium", registry=registry, executor=executor)` is invoked,
- **Then** it returns an active `RuntimeTask` instance.

### AC-CAL-008b: Factory Method Lifecycle Boundary Enforcement
- **Given** an initialized runtime,
- **When** `runtime.model(profile="controlled_agent")` is called synchronously,
- **Then** it raises `CapabilityError` immediately at factory call time with the prescriptive message directing the caller to `runtime.task()`.
- **When** `await runtime.task(profile="controlled_turn")` is called,
- **Then** it raises `CapabilityError` indicating external context requires `runtime.model()`.
- **When** `await runtime.session(profile="controlled_agent")` is called,
- **Then** it raises `CapabilityError` indicating ephemeral profiles cannot create durable sessions.

### AC-CAL-008c: Task-Scoped Instructions
- **Given** a task created with `await runtime.task(instructions="Instructions A", registry=registry, executor=executor)`,
- **When** multiple turns are executed via `task.ainvoke()`,
- **Then** the provider thread maintains `"Instructions A"` across all turns without caller resending them.
- **When** `task.instructions` is inspected,
- **Then** it returns `"Instructions A"`, and attempting to assign to `task.instructions` raises `AttributeError` (read-only property).

### AC-CAL-008d: Active Task Registry & Resolution
- **Given** an active `RuntimeTask` with identifier `task_id` (created with valid tool bindings),
- **When** `runtime.get_task(task_id)` is called,
- **Then** it returns the active task instance.
- **When** `task.close()` is called,
- **Then** `task_id` is removed from the registry, and subsequent `runtime.get_task(task_id)` calls raise `SessionNotFoundError`.
- **When** both `proteo_task_id` and `proteo_session_id` are provided in `RunnableConfig`,
- **Then** `RuntimeNode` raises `ConfigurationError`.

### AC-CAL-008e: Mandatory Host Tool Bindings for `controlled_agent`
- **Given** an initialized runtime,
- **When** `await runtime.task(profile="controlled_agent", registry=None, executor=None)` is called,
- **Then** it raises `CapabilityError("A host-tool registry is required for this profile")` before creating provider context.
- **When** `await runtime.task(profile="controlled_agent", registry=None, executor=executor)` is called with only an executor and no registry,
- **Then** it raises `CapabilityError("A host-tool registry is required for this profile")` via the entry guard before delegating to tool binding.
- **When** `await runtime.task(profile="controlled_agent", registry=empty_registry)` is called where `empty_registry` has no tools,
- **Then** it raises `CapabilityError("A host-tool registry must contain at least one tool")` before creating provider context.
- **When** `await runtime.task(profile="controlled_agent", registry=valid_registry, executor=None)` is called with a valid non-empty registry and omitted executor,
- **Then** task creation succeeds and the runtime constructs a default compatible `ToolExecutor(snapshot)`.
- **When** `await runtime.task(profile="controlled_agent", registry=valid_registry, executor=matching_executor)` is called with a matching executor,
- **Then** task creation succeeds.
- **When** `await runtime.task(profile="controlled_agent", registry=valid_registry, executor=mismatched_executor)` is called with an executor whose snapshot does not match the registry snapshot,
- **Then** it raises `CapabilityError("Tool executor does not match the registry snapshot")` before creating provider context.

### AC-CAL-008f: Codex Task Instructions Wire Protocol Translation
- **Given** an initialized `CodexRuntime` creating a `controlled_agent` task with `instructions="Instructions A"`,
- **When** the runtime calls the compatibility bridge `experimental.start_thread(..., developer_instructions="Instructions A")`,
- **Then** the bridge translates the Python argument to `"developerInstructions": "Instructions A"` in the raw request payload sent to `_client.thread_start(raw)`,
- **And** the key `"developer_instructions"` is not present in `raw`,
- **And** `baseInstructions` is not replaced, cleared, or overwritten.

### AC-CAL-009: Non-Resumability Guard & SessionCodec Protection
- **Given** an initialized runtime (`CodexRuntime` or `FakeRuntime`),
- **When** `await runtime.resume_session(task_id)` is called with an active or closed task ID starting with `task_`,
- **Then** it fails fast before calling `SessionCodec.decode()` by raising `SessionNotFoundError(f"Task '{task_id}' is ephemeral and cannot be resumed as a session")`,
- **And** `SessionCodec.decode()` is never invoked for identifiers in the reserved `task_` namespace (preventing `SessionMismatchError` or syntax errors),
- **And** calling `resume_session(descriptor)` with non-task identifiers continues normal `SessionCodec` processing,
- **And** the `RuntimeTask` handle does not provide `archive()` or `delete()` methods, and does not expose a `SessionDescriptor`.

### AC-CAL-010: Single-Active-Turn Concurrency Enforcement
- **Given** an active `RuntimeTask` (created with valid tool bindings) executing a turn,
- **When** a concurrent call to `ainvoke()` or `astream()` is made on the same task,
- **Then** the second call raises `SessionBusyError("Task already has an active turn")` immediately without executing provider inference.

### AC-CAL-010b: Hardened Context Replay Protection
- **Given** an active `RuntimeTask` with `ContextPolicy.RUNTIME` (created with valid tool bindings),
- **When** `task.ainvoke(input)` is called with a `RuntimeInput` containing any `RuntimeMessage` with role `system`, `assistant`, or `tool`,
- **Then** `ContextPolicyError("Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; replaying 'assistant', 'tool', or injecting 'system' messages is prohibited.")` is raised before inference begins.
- **When** `task.ainvoke(input)` is called with a `str` or `RuntimeInput` containing only `user` role messages,
- **Then** execution proceeds normally.

### AC-CAL-011: Post-Close Invalidation
- **Given** a `RuntimeTask` (created with valid tool bindings) in `CLOSED` state,
- **When** `task.ainvoke()`, `task.astream()`, or `task.interrupt()` is called,
- **Then** the call raises `SessionNotFoundError("Task '{task_id}' not found or already closed")`.

### AC-CAL-011b: Teardown Race Prevention & State Machine Invalidation
- **Given** an active `RuntimeTask` in state `OPEN`,
- **When** `task.close()` begins and transitions state from `OPEN` to `CLOSING`,
- **Then** any new or external call to `task.ainvoke()`, `task.astream()`, or `task.interrupt()` during the teardown window fails immediately before provider inference, tool execution, or SDK routing by raising `SessionNotFoundError(f"Task '{task_id}' not found or already closed")`,
- **And** `task.close()` cancels any ongoing active turn directly using the internal cancellation primitive without calling public `task.interrupt()`,
- **And** concurrent calls to `task.close()` do not duplicate cleanup operations,
- **And** the `TASK_CLOSED` runtime event is emitted strictly once upon completion of teardown.

### AC-CAL-012: Provider Ephemeral Thread Reuse
- **Given** `CodexRuntime` executing a `controlled_agent` task (created with valid tool bindings),
- **When** Turn 1 and Turn 2 are executed sequentially,
- **Then** both turns call `thread.turn(...)` on the identical underlying Codex thread instance.

### AC-CAL-013: Task Workspace Directory Lifecycle
- **Given** a `controlled_agent` task in `CodexRuntime` (created with valid tool bindings),
- **When** the task is initialized,
- **Then** an isolated workspace directory is created on disk.
- **When** `await task.close()` finishes,
- **Then** the temporary directory is completely removed from the filesystem.

### AC-CAL-014: Task Teardown and Cleanup Sequence
- **Given** an active `RuntimeTask` (created with valid tool bindings),
- **When** `await task.close()` is executed,
- **Then** if a turn is active, turn cancellation is requested directly via the internal cancellation primitive (without calling public `task.interrupt()`), `ToolExecutor.end_invocation(active_invocation_id)` is called, tool bridge routes are unregistered, the provider thread is released/destroyed, the workspace is deleted, the task is removed from `runtime._tasks`, and `RuntimeEventKind.TASK_CLOSED` is emitted.

### AC-CAL-014b: Idempotent `close()` and Cleanup Resilience
- **Given** a `RuntimeTask` (created with valid tool bindings),
- **When** `await task.close()` is called a second time,
- **Then** it returns `None` immediately without error, and `TASK_CLOSED` is emitted only once.
- **When** an error occurs during a cleanup step (such as workspace directory deletion),
- **Then** remaining cleanup steps continue best-effort, a diagnostic failure is logged, and the handle remains closed and unusable.

### AC-CAL-015: Frozen Semantic Configuration & Authority
- **Given** a `RuntimeTask` created with a specific tool registry snapshot and permission policy,
- **When** the task is active,
- **Then** dynamic tool schema mutation or authority expansion is strictly blocked.

### AC-CAL-015b: Per-Turn `InvocationConfig` Validation
- **Given** an active `RuntimeTask` (created with valid tool bindings),
- **When** `task.ainvoke(config=InvocationConfig(model="other-model"))` is called,
- **Then** `ConfigurationError` is raised before inference begins.
- **When** `task.ainvoke(config=InvocationConfig(timeout_seconds=15.0))` is called,
- **Then** the timeout override is accepted and applied.

### AC-CAL-016: Per-Turn Invocation Identification
- **Given** a `RuntimeTask` (created with valid tool bindings) executing multiple turns,
- **When** inspecting events and tool execution records,
- **Then** each turn has a unique `turn_id` / `invocation_id` while sharing the identical `task_id`.

### AC-CAL-017: `ToolExecutor.end_invocation()` Per-Turn Hook
- **Given** a turn with `invocation_id=X`,
- **When** the turn completes or fails,
- **Then** `ToolExecutor.end_invocation(X)` is called.
- **And** given an active turn with `invocation_id=X` when `task.close()` executes, `ToolExecutor.end_invocation(X)` is called.

### AC-CAL-018: Dynamic Tool Execution via Multiplexer & Route Resolution
- **Given** a `controlled_agent` `RuntimeTask` with registered host tools,
- **When** the provider emits an `item/tool/call` on an active turn,
- **Then** `CodexToolMux` resolves the route matching the active thread and turn,
- **And** `CodexToolBridge` constructs a `ToolRequest` with stable `task_id=task.id`, turn `invocation_id`, turn `turn_id`, and `session_id=None`,
- **And** `ToolExecutor` executes the tool and returns the response to the provider,
- **And** all tool events (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`) contain `task_id=task.id`,
- **When** a tool call arrives on an unknown or unregistered multiplexer route,
- **Then** the call fails closed without executing tools or leaking state.

### AC-CAL-019: LangGraph `RuntimeNode` Task Routing
- **Given** a `RuntimeNode` configured with `configurable={"proteo_task_id": "task_123"}`,
- **When** the node is invoked,
- **Then** it resolves the task from `runtime.get_task("task_123")` and executes `task.ainvoke()`.

### AC-CAL-020: Distinct Ephemeral Task Capability (`ephemeral_tasks`)
- **Given** `RuntimeCapabilities` in `capabilities.py`,
- **When** inspected,
- **Then** it declares `ephemeral_tasks: bool = False` as default.
- **When** `CodexRuntime.capabilities()` is inspected on a supporting provider instance,
- **Then** it advertises `ephemeral_tasks=True`.
- **When** `FakeRuntime.capabilities()` is inspected with default settings,
- **Then** it advertises `ephemeral_tasks=True`.
- **When** a runtime configured with `ephemeral_tasks=False` is asked to create a `controlled_agent` task via `runtime.task(profile="controlled_agent", ...)`,
- **Then** it raises `CapabilityError` before creating any provider thread or allocating task handles.

### AC-CAL-021: Complete Observability & Correlation Propagation
- **Given** a multi-turn task execution with host tool calls,
- **When** turn events, tool lifecycle events, and OpenTelemetry spans are emitted,
- **Then** all turn events, `RuntimeResult`, and spans contain `task_id` (with `RuntimeEvent.task_id` defined in `events.py` and `RuntimeResult.task_id` defined in `model.py`),
- **And** all tool events (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_DENIED`, retries) contain `task_id` copied from `ToolRequest.task_id` (defined in `tools/__init__.py`),
- **And** `turn_id` is unique per turn,
- **And** `session_id` is strictly `None` across all task events and tool requests/events,
- **And** LangSmith metadata contains `proteo_task_id`,
- **And** raw Codex thread IDs are absent from all public telemetry and events.

### AC-CAL-022: Smart Quote Agent Migration
- **Given** `examples/smart_quote_agent/app.py`,
- **When** inspected,
- **Then** it initializes its model with `runtime.model(profile="controlled_turn", level="low")`, `graph.py` binds `controlled_turn`, `README.md` documents `controlled_turn`, and its tests in `tests/test_agent.py` pass.

### AC-CAL-023: Unit Test Suite
- **Given** the repository unit test suite,
- **When** `uv run pytest tests/unit/core/test_controlled_profiles.py tests/unit/tools/test_controlled_agent.py` is executed,
- **Then** all tests pass.

### AC-CAL-024: Live Codex Multi-Turn Smoke Test
- **Given** `tests/integration/codex/test_codex_controlled_agent.py`,
- **When** executed with `PROTEO_CODEX_INTEGRATION=1` under an active Codex subscription login (`codex login`),
- **Then** `await runtime.start()` pre-flight succeeds (skipping cleanly if unauthenticated), multi-turn context reuse succeeds with tool execution, a second task starts with a clean context, and zero `OPENAI_API_KEY` is required.

### AC-CAL-025: Design Guide Synchronization
- **Given** `docs/design/project-guide.md`,
- **When** reviewed,
- **Then** profile definitions, `RuntimeTask` lifecycle, and factory boundaries match the SDD specifications.

### AC-CAL-026: Validate and Synchronize ADR 0004
- **Given** `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md`,
- **When** reviewed,
- **Then** its contents remain fully aligned with the decisions in this SDD package.
