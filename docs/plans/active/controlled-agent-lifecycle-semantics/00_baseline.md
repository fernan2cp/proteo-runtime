# Baseline — Controlled Agent Lifecycle Semantics

## 1. Context & Background

Proteo Runtime provides a uniform abstraction layer over subscription-backed agent reasoning engines (specifically OpenAI Codex via Codex App Server and CLI login) and cloud LLMs. The foundational design principles established in `docs/design/project-guide.md` mandate that:
1. The host/framework owns business, workflow, and global application state, and retains ultimate authority over tools and permissions.
2. The runtime may own task-local conversational context when `ContextPolicy.RUNTIME` is active (as in `controlled_agent` tasks and durable sessions).
3. The runtime engine acts strictly as a controlled reasoning mechanism, operating under explicit security and execution profiles.
4. Host-managed tools are enforced through an explicit registry; native provider tool execution is denied by default.
5. Ephemeral lifecycles must be cleanly isolated and fail closed.

In the initial implementation of Proteo Runtime, the built-in profile `controlled_agent` was defined with:
- `LifecycleMode.EPHEMERAL` (single host invocation)
- `ContextPolicy.EXTERNAL` (host replays or provides all conversational context on every call)
- `HostToolsMode.CONTROLLED` (explicit registry only)
- `SecurityPolicy.CONTROLLED_TOOLS` (host executes tools; native tools denied)

Under this definition, the Codex provider adapter created a new ephemeral thread (`thread_start(ephemeral=True)`) on *every* invocation. While this guaranteed complete isolation between calls, it conflated "ephemeral durability" with "single-turn turn count." Consequently, multi-turn agent workflows (such as multi-step coding or research tasks) were unable to leverage the provider's local context window across turns unless they either:
- Replayed full message history on every turn (wasteful, expensive, and error-prone), or
- Switched to a persistent `session` (incurring unnecessary durability, persistence descriptors, and storage management for purely throwaway tasks).

Furthermore, calling `runtime.model(profile="controlled_agent")` posed an architectural ambiguity: should `RuntimeModel` silently retain context across calls (violating the invocation-scoped contract of `RuntimeModel` and risking cross-user contamination), or silently degrade to one-shot execution (violating the profile's multi-turn intent)?

## 2. Source of Truth & Design Authority

This SDD package is governed by:
- `docs/design/project-guide.md`: The primary design source of truth (Sections 7.2, 7.3, 9.4, 9.5, 10.1, 10.2, 10.3, 11.2, 12.3, 13.1, 15.1, 18.1).
- `docs/adr/0001-runtime-boundary-and-project-scope.md`: Scope and boundaries of the runtime.
- `docs/adr/0003-host-managed-tools.md`: Host-owned tool execution and dynamic multiplexing.
- `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md`: Existing, accepted ADR establishing the split into `controlled_turn` and `controlled_agent` and introducing `RuntimeTask`.

## 3. Current Implementation Audit

An inspection of commit `ade0b96` on branch `arch/controlled-execution-profiles` reveals the following repository state:

### 3.1 Profiles & Configuration Subsystem
- `src/proteo_runtime/core/profiles.py`:
  - `DEFAULT_PROFILE_SPECS` defines `controlled_agent` with `ContextPolicy.EXTERNAL` and `LifecycleMode.EPHEMERAL`.
  - `controlled_turn` does not yet exist in `DEFAULT_PROFILE_SPECS` or `ExecutionProfileName`.
- `src/proteo_runtime/config/models.py`:
  - `RuntimeConfigV1` validates profiles against `DEFAULT_PROFILE_SPECS`.
- `src/proteo_runtime/config/defaults/codex_v1.json`:
  - Declares Codex model and reasoning effort mappings for `brain`, `structured`, `session`, and `controlled_agent`.
  - Does not declare mappings for `controlled_turn`.

### 3.2 Runtime Interfaces & Lifecycle Boundaries
- `src/proteo_runtime/core/runtime.py`:
  - `Runtime` protocol exposes synchronous `model(*, profile: str, level: str = "medium") -> RuntimeModel[Any]`, asynchronous `capabilities() -> RuntimeCapabilities`, and asynchronous `session(...)`.
  - It does not expose `task(...)` or `get_task(...)`.
  - `Runtime.model(...)` currently permits passing any registered profile string, without enforcing lifecycle or context policy compatibility at factory call time.
- `src/proteo_runtime/core/task.py`:
  - Does not exist. No provider-neutral contract exists for task-scoped ephemeral lifecycles.
- `src/proteo_runtime/core/capabilities.py`:
  - `RuntimeCapabilities` defines `ephemeral_sessions: bool = True` and `persistent_sessions: bool = False`.
  - It does not declare `ephemeral_tasks: bool = False`, conflating single-turn ephemeral execution with multi-turn ephemeral task capability.

### 3.3 Provider Implementations
- `src/proteo_runtime/providers/codex/runtime.py`:
  - `CodexRuntime` implements synchronous `Runtime.model(...)`, asynchronous `capabilities()`, and asynchronous `Runtime.session(...)`.
  - `_tool_binding(spec, registry, executor)` validates tool bindings, raising `CapabilityError("A host-tool registry is required for this profile")` if missing, `CapabilityError("A host-tool registry must contain at least one tool")` if empty, and `CapabilityError("Tool executor does not match the registry snapshot")` on mismatch.
  - On every invocation of a model configured with `controlled_agent`, `CodexRuntime` creates a fresh ephemeral thread (`thread_start(ephemeral=True)`), executes the turn, and immediately unregisters tool routes, destroying the ephemeral context.
  - Does not implement an in-memory task registry `_tasks: dict[str, RuntimeTask[Any]]`.
  - `CodexRuntime.start()` encapsulates the startup and validation of Codex subscription credentials (`sdk.account()`), raising `AuthenticationError` if unauthenticated.
- `src/proteo_runtime/testing/fakes.py`:
  - `FakeRuntime` mirrors `CodexRuntime` factory methods but lacks `task(...)` support and task registry tracking.

### 3.4 Tools & Invocation Scoping
- `src/proteo_runtime/tools/__init__.py`:
  - Provider-neutral tool contracts: `ToolRequest`, `ToolExecutor`, `ToolRegistry`, `ToolSnapshot`.
  - `ToolExecutor.end_invocation(invocation_id)` cleans up per-turn tool execution state.
  - Tool authority is host-side, but dynamic schema mutation and mid-task instruction overrides are not strictly guarded against frozen task authority.
- `src/proteo_runtime/providers/codex/experimental.py`:
  - Provider-specific Codex dynamic tool integration: `CodexToolBridge`, `CodexToolMux`, `start_thread`, compatibility bridge.
  - `CodexToolBridge` routes provider tool calls into `ToolExecutor` using turn-level invocation IDs (`invocation_id`).

### 3.5 Integrations & Examples
- `src/proteo_runtime/integrations/langgraph/node.py`:
  - `RuntimeNode` supports one-shot models and durable sessions via `proteo_session_id`.
  - Does not support ephemeral tasks or `proteo_task_id`.
  - Does not enforce mutual exclusion between `proteo_task_id` and `proteo_session_id`.
- `examples/smart_quote_agent/app.py`:
  - Uses `runtime.model(profile="controlled_agent", level="low")` (Line 159) for an invocation-scoped single-turn reasoning node with external context. This usage, along with its graph wiring in `graph.py`, documentation in `README.md`, and test suite in `tests/test_agent.py`, must be migrated to `controlled_turn`.

## 4. Closed Architectural Decisions

The following 17 architectural decisions are firmly established and closed:

1. **Profile Split**:
   - `controlled_turn`: Preserves existing one-shot behavior (`LifecycleMode.EPHEMERAL`, `ContextPolicy.EXTERNAL`, `HostToolsMode.CONTROLLED`, `SecurityPolicy.CONTROLLED_TOOLS`). Starts with a clean runtime context on every invocation.
   - `controlled_agent`: Re-defined as task-scoped stateful ephemeral execution (`LifecycleMode.EPHEMERAL`, `ContextPolicy.RUNTIME`, `HostToolsMode.CONTROLLED`, `SecurityPolicy.CONTROLLED_TOOLS`). Reuses the same provider task context across all turns within the task. Discarded completely upon task completion. Strictly non-resumable.

2. **Factory Lifecycle Boundary Enforcement (Fail-Fast)**:
   - `runtime.model(profile="controlled_agent")` is synchronous and MUST fail immediately at factory call time with `CapabilityError`.
   - Message: `"Profile 'controlled_agent' has runtime context and requires an explicit task lifecycle via runtime.task(); use 'controlled_turn' for invocation-scoped model execution."`
   - `runtime.model(...)` is strictly restricted to `ContextPolicy.EXTERNAL` + `LifecycleMode.EPHEMERAL`.
   - `runtime.task(...)` is strictly restricted to `ContextPolicy.RUNTIME` + `LifecycleMode.EPHEMERAL`.
   - `runtime.session(...)` is strictly restricted to `LifecycleMode.PERSISTENT`.
   - Zero silent degradation, zero hidden sticky state.

3. **Mandatory Host Tool Bindings for `controlled_agent`**:
   - `controlled_agent` strictly requires valid host tool bindings.
   - Call pattern: `await runtime.task(profile="controlled_agent", level="medium", registry=registry, executor=executor, ...)`
   - Creating a `controlled_agent` task without `registry` and `executor` raises `CapabilityError("A host-tool registry is required for this profile")`.
   - Providing an empty registry raises `CapabilityError("A host-tool registry must contain at least one tool")`.
   - Providing an executor with a mismatched snapshot raises `CapabilityError("Tool executor does not match the registry snapshot")`.
   - No silent fallback, no implicit empty registry.

4. **Task-Scoped Instructions for `controlled_agent`**:
   - Provided at task creation via `await runtime.task(profile="controlled_agent", instructions="...", registry=registry, executor=executor)`.
   - Frozen for the entire life of the task; applies to all turns.
   - Caller does NOT resend per turn; not part of host conversational history or business state.
   - `RuntimeTask` exposes `instructions: str | None` as a read-only property.
   - Mapped in Python to `start_thread(..., developer_instructions=instructions)`; the compatibility bridge (`experimental.start_thread()`) explicitly translates `developer_instructions -> developerInstructions` on the raw App Server wire protocol, leaving provider base instructions (`baseInstructions`) completely intact.
   - No per-turn API exists to modify or replace instructions. `InvocationConfig` intentionally does NOT declare an `instructions` field, precluding per-turn mutation.
   - Provider-neutral and respects redaction/observability policies.

5. **Hardened Context Replay Protection (User-Only Input)**:
   - `RuntimeTask.ainvoke(input: str | RuntimeInput, ...)` and `astream(input: str | RuntimeInput, ...)` accept neutral input.
   - A plain `str` input is treated as a single message with role `user`.
   - Under `ContextPolicy.RUNTIME`, the caller may ONLY provide new `user` message input for the current turn.
   - Any `RuntimeInput` containing messages with role `system`, `assistant`, or `tool` fails before inference with `ContextPolicyError("Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; replaying 'assistant', 'tool', or injecting 'system' messages is prohibited.")`.
   - The neutral `RuntimeMessage` contract only admits `Literal["system", "user", "assistant", "tool"]`; `developer` is not a message role.
   - Prevents transcript replay, prevents indirect instruction replacement, and prevents per-turn developer or system instruction injection (developer instructions exist exclusively via `runtime.task(instructions=...)`).
   - The host owns business/workflow state, not the technical conversation transcript of the task.

6. **Separate Capabilities (`ephemeral_tasks` vs `ephemeral_sessions`)**:
   - Add `ephemeral_tasks: bool = False` to `RuntimeCapabilities`.
   - Capabilities are accessed asynchronously via `await runtime.capabilities()`.
   - `CodexRuntime.capabilities()` explicitly advertises `ephemeral_tasks=True` when provider capabilities are active.
   - `FakeRuntime` explicitly advertises `ephemeral_tasks=True` by default to enable test suites.
   - Any runtime that does not support task-scoped multi-turn context maintains `ephemeral_tasks=False`.
   - `controlled_agent` requires `host_tools=True` and `ephemeral_tasks=True`.
   - `controlled_turn` requires `host_tools=True` and `ephemeral_sessions=True`, but does NOT require `ephemeral_tasks`.
   - Distinct capability matrix: ephemeral invocation (`ephemeral_sessions`), ephemeral multi-turn task (`ephemeral_tasks`), and persistent session (`persistent_sessions`).

7. **Active `RuntimeTask` Registry & Lifecycle**:
   - Owned by the runtime implementation (`runtime._tasks: dict[str, RuntimeTask[Any]]`).
   - `RuntimeTask.id` generated by Proteo (`f"task_{uuid.uuid4().hex}"`), opaque to callers, never exposing raw provider thread IDs.
   - Unique per runtime instance, used for in-memory routing and correlation.
   - Registered upon creation; removed upon `task.close()` or `runtime.close()`.
   - Unknown or closed `task_id` raises `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
   - Does not survive runtime process restart.
   - Mutual exclusion: having both `proteo_task_id` and `proteo_session_id` in `RunnableConfig` raises `ConfigurationError`.

8. **Freezing Semantic Configuration & Authority**:
   - Frozen at task creation: profile, resolved model, reasoning effort, context policy, security policy, task instructions, tool registry snapshot, tool executor, permission policy, approval handler, workspace sandbox policy.
   - `InvocationConfig` audit:
     - Allowed per turn: `timeout_seconds`, `include_raw`, `metadata`.
     - Prohibited per turn: `model` (if != frozen model), `reasoning_effort` (if != frozen effort), tool schema/authority modifications.
     - Prohibited overrides raise `ConfigurationError` before inference; never silently ignored.

9. **Observability & Correlation Propagation (Accurate Module Boundaries)**:
   - `task_id` correlates all events originating within the task: invocation events, turn events, tool events, retry events, validation events, `TASK_STARTED`, `TASK_CLOSED`.
   - `TASK_STARTED`, `TASK_CLOSED`, and `RuntimeEvent.task_id` belong to `src/proteo_runtime/core/events.py`.
   - `RuntimeResult.task_id` belongs to `src/proteo_runtime/core/model.py`.
   - Propagates to LangSmith metadata (`proteo_task_id`) and OpenTelemetry span attributes (`proteo.task_id`).
   - Rules: `task_id` stable across turns; `turn_id` / `invocation_id` unique per turn; `session_id = None` for tasks; raw provider thread ID never leaked.
   - `task_id` is NOT added to low-cardinality metric labels.

10. **Deterministic Error Taxonomy (Zero "or")**:
    - Concurrency conflict (concurrent turn on same task): `SessionBusyError("Task already has an active turn")`.
    - Unknown or closed task ID / calling methods on closed task: `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
    - Incompatible profile / missing capability / missing or invalid tool bindings: `CapabilityError`.
    - Invalid turn configuration override: `ConfigurationError`.
    - Context replay / non-user role injection attempt: `ContextPolicyError`.

11. **Exact `RuntimeTask.close()` Semantics & Teardown Sequence**:
    - `close()` is idempotent: first call executes teardown; second call is a safe no-op returning `None`.
    - Exact teardown sequence:
      1. Mark task closing (`self._state = TaskState.CLOSING`).
      2. If turn is active: request turn cancellation directly via internal cancellation primitive (without calling public `task.interrupt()`), wait bounded cancellation grace period (default 5.0s).
      3. Invalidate provider context if cleanup cannot be confirmed.
      4. Unregister tool bridge and dynamic multiplexer routes.
      5. Call `executor.end_invocation(active_invocation_id)` for active turn.
      6. Release/destroy provider task context where supported (Codex SDK ephemeral thread).
      7. Remove temporary workspace directory.
      8. Remove task from active registry (`runtime._tasks`).
      9. Mark closed.
      10. Emit `TASK_CLOSED`.
    - Cleanup failure handling: log diagnostic failure, continue best-effort with remaining steps, handle remains unusable/closed, do not reopen task.

12. **Live Codex Smoke Test Authentication**:
    - Uses Codex-managed subscription authentication via Codex App Server and CLI login (`codex login`).
    - Pre-flight check uses normal `await runtime.start()`. If missing or invalid authentication, `runtime.start()` raises `AuthenticationError`, which the test catches and converts to `pytest.skip("Codex subscription login is not active; skipping live integration tests.")`.
    - Opt-in via `PROTEO_CODEX_INTEGRATION=1` and `-m integration`.
    - Zero reliance on `OPENAI_API_KEY`. No custom OAuth flow or invented SDK APIs.

13. **ADR 0004 Status**:
    - ADR 0004 already exists as an accepted document at `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md`.
    - Task `CAL-TASK-0026` and requirement `CAL-REQ-026` validate and synchronize ADR 0004 against final SDD decisions.

14. **Formal Semantics of `RuntimeTask.id`**:
    - Provider-neutral, Proteo-generated opaque string (`f"task_{uuid.uuid4().hex}"`).
    - Exclusively an in-memory routing and telemetry correlation token.
    - NOT a credential, NOT an authorization boundary, NOT a persistence handle, NOT a `SessionDescriptor`.

15. **Bounded Shared Engine (`_StatefulContext` / `_ThreadRunner`)**:
    - Shared mechanics between `_CodexTask` and `_CodexSession` are strictly bounded to: single-active-turn lock (`asyncio.Lock`), turn execution flow, event streaming plumbing, tool bridge turn dispatch, timeout/cancellation plumbing, per-turn `end_invocation` cleanup, context replay checks.
    - Strictly EXCLUDES: `SessionDescriptor`, persistence, resume, archive/delete, session migration, task registry, ephemeral workspace destruction.

16. **Preservation of Resolved Architecture**:
    - `controlled_turn` as the one-shot profile.
    - `controlled_agent` as the task-scoped ephemeral profile.
    - Host-owned tool execution and per-turn `end_invocation(invocation_id)`.
    - Smart Quote Agent migration to `controlled_turn` across `app.py`, `graph.py`, `README.md`, and `tests/test_agent.py`.

17. **Decision-Complete Status**:
    - All requirements, technical designs, task plans, acceptance criteria, validation scenarios, and rollout plans are complete, internally consistent, and ready for implementation.
