# Technical Design — Controlled Agent Lifecycle Semantics

## 1. Architectural Overview

The Proteo Runtime provides a uniform, provider-neutral abstraction layer for agent reasoning engines. To support both single-turn controlled reasoning and multi-turn stateful agent tasks without conflating durability with turn count, the runtime defines two distinct built-in profiles:

```text
controlled_turn
    Lifecycle:        LifecycleMode.EPHEMERAL (invocation-scoped)
    Context:          ContextPolicy.EXTERNAL (host provides history)
    Tools:            HostToolsMode.CONTROLLED (explicit registry only)
    Security:         SecurityPolicy.CONTROLLED_TOOLS (host execution, native denied)
    Behavior:         Clean runtime context on every invocation; zero cross-call memory.

controlled_agent
    Lifecycle:        LifecycleMode.EPHEMERAL (task-scoped)
    Context:          ContextPolicy.RUNTIME (Proteo owns task-local conversation)
    Tools:            HostToolsMode.CONTROLLED (explicit registry only; required)
    Security:         SecurityPolicy.CONTROLLED_TOOLS (host execution, native denied)
    Behavior:         Reuses the same live provider thread across turns within the task;
                      context is discarded when the task closes; non-resumable.
```

The boundary between invocation-scoped models, task-scoped ephemeral agents, and durable sessions is made explicit across the public API:
- `runtime.model(...)` creates an invocation-scoped `RuntimeModel` synchronously.
- `runtime.task(...)` creates a task-scoped ephemeral `RuntimeTask` asynchronously.
- `runtime.session(...)` creates a durable, resumable `RuntimeSession` asynchronously.

---

## 2. Core Interfaces & Public Contracts

### 2.1 `RuntimeTask[T]` Protocol Contract

Created in `src/proteo_runtime/core/task.py` and exported from `proteo_runtime`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Generic, Protocol, TypeVar
from proteo_runtime.core.input import RuntimeInput
from proteo_runtime.core.model import InvocationConfig, RuntimeResult
from proteo_runtime.core.events import RuntimeEvent

T = TypeVar("T")

class RuntimeTask(Protocol, Generic[T]):
    """Explicit lifecycle boundary for a task-scoped ephemeral controlled agent."""

    @property
    def id(self) -> str:
        """Provider-neutral, Proteo-generated opaque task identifier."""
        ...

    @property
    def instructions(self) -> str | None:
        """Initial task instructions frozen at task creation (read-only)."""
        ...

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[T]:
        """Execute one turn within the task, reusing the task's runtime context."""
        ...

    def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream runtime events for one turn within the task."""
        ...

    async def interrupt(self) -> None:
        """Interrupt the currently active turn in this task."""
        ...

    async def close(self) -> None:
        """Idempotently discard runtime context and release provider resources."""
        ...

    async def __aenter__(self) -> RuntimeTask[T]:
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        ...
```

### 2.2 `Runtime` Factory Signatures

`src/proteo_runtime/core/runtime.py` defines the factory methods on `Runtime`:

```python
class Runtime(Protocol):
    def model(self, *, profile: str, level: str = "medium") -> RuntimeModel[Any]:
        """Create a synchronous model view for an invocation-scoped profile and logical level."""
        ...

    async def task(
        self,
        profile: str = "controlled_agent",
        *,
        level: str = "medium",
        instructions: str | None = None,
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeTask[Any]:
        """Create an ephemeral task-scoped execution handle."""
        ...

    def get_task(self, task_id: str) -> RuntimeTask[Any]:
        """Resolve an active, in-memory task by its identifier."""
        ...

    async def session(
        self,
        profile: str = "session",
        *,
        level: str = "medium",
        config: Any | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeSession[Any]:
        """Create a resumable session."""
        ...
```

### 2.3 `RuntimeCapabilities` Separation

`src/proteo_runtime/core/capabilities.py` adds `ephemeral_tasks` as an independent capability:

```python
@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Immutable feature support advertised by a runtime."""

    structured_output: bool = False
    ephemeral_sessions: bool = True     # One-shot ephemeral thread/invocation support
    ephemeral_tasks: bool = False        # Multi-turn ephemeral task context reuse support
    persistent_sessions: bool = False   # Durable resumable session support
    streaming: bool = True
    interruption: bool = False
    host_tools: bool = False
    native_tools: bool = False
    sandbox: bool = True
    usage_reporting: bool = True
```

Capability enforcement across profiles:
| Profile | Required Capabilities |
|---|---|
| `brain` | `ephemeral_sessions=True` |
| `structured` | `structured_output=True`, `ephemeral_sessions=True` |
| `controlled_turn` | `host_tools=True`, `ephemeral_sessions=True` |
| `controlled_agent` | `host_tools=True`, `ephemeral_tasks=True` |
| `session` | `persistent_sessions=True` |

### Provider Implementation & Advertising

1. **`CodexRuntime.capabilities()` (`src/proteo_runtime/providers/codex/runtime.py`)**:
   Explicitly advertises `ephemeral_tasks=True` when provider capabilities are active:
   ```python
   async def capabilities(self) -> RuntimeCapabilities:
       """Return the provider capabilities available in Phase 2."""
       return RuntimeCapabilities(
           structured_output=True,
           ephemeral_sessions=True,
           ephemeral_tasks=True,  # Advertised for task-scoped multi-turn context support
           persistent_sessions=True,
           streaming=True,
           interruption=True,
           host_tools=self._dynamic_tools_compatibility.supported,
           native_tools=False,
           sandbox=True,
           usage_reporting=True,
       )
   ```

2. **`FakeRuntime` Default Capabilities (`src/proteo_runtime/testing/fakes.py`)**:
   Explicitly sets `ephemeral_tasks=True` by default so test suites can exercise `RuntimeTask` without manual overrides:
   ```python
   self._capabilities = capabilities or RuntimeCapabilities(
       structured_output=True,
       ephemeral_sessions=True,
       ephemeral_tasks=True,  # Default True for test fidelity and task simulation
       persistent_sessions=True,
       streaming=True,
       interruption=True,
       host_tools=True,
       native_tools=False,
       sandbox=True,
       usage_reporting=True,
   )
   ```

3. **Propagation in `effective_capabilities()`**:
   Both `_CodexModel.effective_capabilities()` and `_FakeModel.effective_capabilities()` propagate `ephemeral_tasks=capabilities.ephemeral_tasks` to ensure consistency.

4. **Non-Supporting Runtimes**:
   Any runtime that does not implement task-scoped multi-turn context leaves `ephemeral_tasks=False`, immediately failing fast on `runtime.task(...)`.

---

## 3. Factory Lifecycle Boundaries & Invariants

Factory methods strictly validate profile lifecycle, context policy, capabilities, and required tool bindings at call time:

| Factory Method | Calling Convention | Allowed Context Policy | Allowed Lifecycle | Target Profiles | Rejection Behavior (Fail-Fast) |
|---|---|---|---|---|---|
| `runtime.model(...)` | Synchronous (`def`) | `ContextPolicy.EXTERNAL` | `LifecycleMode.EPHEMERAL` | `brain`, `structured`, `controlled_turn` | Raises `CapabilityError` if profile is `controlled_agent`, `session`, or `native`. |
| `runtime.task(...)` | Asynchronous (`async def`) | `ContextPolicy.RUNTIME` | `LifecycleMode.EPHEMERAL` | `controlled_agent` | Raises `CapabilityError` if profile has `ContextPolicy.EXTERNAL` (`controlled_turn`, `brain`), is persistent (`session`), or lacks tool bindings. |
| `runtime.session(...)` | Asynchronous (`async def`) | `ContextPolicy.RUNTIME` or `HYBRID` | `LifecycleMode.PERSISTENT` | `session` | Raises `CapabilityError` if profile is ephemeral (`controlled_agent`, `controlled_turn`). |

### Exact Validation & Dispatch Logic in `CodexRuntime` / `FakeRuntime`:

```python
# In runtime.model(...) — Synchronous method!
spec = profile_spec(profile)
if spec.context is ContextPolicy.RUNTIME and spec.lifecycle is LifecycleMode.EPHEMERAL:
    raise CapabilityError(
        f"Profile '{profile}' has runtime context and requires an explicit task lifecycle "
        f"via runtime.task(); use 'controlled_turn' for invocation-scoped model execution."
    )
if spec.lifecycle is LifecycleMode.PERSISTENT:
    raise CapabilityError(f"Profile '{profile}' is persistent; use runtime.session() for durable sessions.")

# In runtime.task(...) — Asynchronous method
capabilities = await self.capabilities()
if not capabilities.ephemeral_tasks:
    raise CapabilityError(f"Runtime '{self.name}' does not support ephemeral multi-turn tasks.")
spec = profile_spec(profile)
if spec.context is ContextPolicy.EXTERNAL:
    raise CapabilityError(f"Profile '{profile}' has external context; use runtime.model() for invocation-scoped execution.")
if spec.lifecycle is LifecycleMode.PERSISTENT:
    raise CapabilityError(f"Profile '{profile}' is persistent; use runtime.session() for durable sessions.")

# Validate mandatory host tool bindings for controlled_agent
if registry is None:
    raise CapabilityError("A host-tool registry is required for this profile")
tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
```

---

## 4. Mandatory Tool Bindings & Task Instructions

### 4.1 Mandatory Tool Bindings for `controlled_agent`

`controlled_agent` strictly requires host tool authority. When creating a task via `runtime.task(profile="controlled_agent", ...)`:
- `registry` is **mandatory**.
- `executor` is **optional**.

`Runtime.task()` enforces an explicit entry guard before invoking `_tool_binding()`:
```python
if registry is None:
    raise CapabilityError("A host-tool registry is required for this profile")
```
This ensures callers cannot create a `controlled_agent` task by providing only an `executor` without a `registry` (since `_tool_binding()` alone would otherwise accept `registry=None, executor=<ToolExecutor>`).

If `executor` is omitted (`executor=None`), the runtime constructs a default `ToolExecutor` compatible with `registry.snapshot()`.

#### Exact Validation Matrix:

| Registry Parameter | Executor Parameter | Outcome |
|---|---|---|
| `registry=None` | `executor=None` | Raises `CapabilityError("A host-tool registry is required for this profile")` |
| `registry=None` | `executor=executor` | Raises `CapabilityError("A host-tool registry is required for this profile")` |
| `registry=empty_registry` | Any / `None` | Raises `CapabilityError("A host-tool registry must contain at least one tool")` |
| `registry=valid_registry` | `executor=None` | **Valid**; runtime constructs compatible `ToolExecutor(snapshot)` |
| `registry=valid_registry` | `executor=matching_executor` | **Valid** |
| `registry=valid_registry` | `executor=mismatched_executor` | Raises `CapabilityError("Tool executor does not match the registry snapshot")` |

Valid creation pattern:
```python
task = await runtime.task(
    profile="controlled_agent",
    level="medium",
    instructions="You are a data validation specialist. Always format numbers with two decimals.",
    registry=registry,
    executor=executor,  # Optional: defaults to compatible ToolExecutor if omitted
)
```

### 4.2 Task-Scoped Instructions & Codex SDK Mapping

Rules & Architecture:
1. **Frozen on Start**: Stored in `RuntimeTask.instructions` (read-only property).
2. **Two-Layer Architecture (Python vs Wire Protocol)**:
   - **Layer 1 (Proteo / Python Caller in `CodexRuntime`)**:
     `CodexRuntime.task(...)` invokes the private dynamic-tools helper using idiomatic Python snake_case:
     ```python
     thread = await start_thread(
         self._sdk,
         dynamic_tools=tool_snapshot,
         ephemeral=True,
         model=model,
         developer_instructions=self._instructions,
         cwd=str(workspace),
         approvalPolicy="never",
         sandboxPolicy="read-only",
     )
     ```
   - **Layer 2 (Compatibility Bridge & Wire Protocol in `experimental.py`)**:
     In `src/proteo_runtime/providers/codex/experimental.py::start_thread()`, the bridge translates `developer_instructions` to camelCase `developerInstructions` before constructing the raw payload for `sdk._client.thread_start(raw)`:
     ```python
     async def start_thread(sdk: Any, *, dynamic_tools: ToolSnapshot, **params: Any) -> Any:
         """Start a thread through the private raw SDK call with dynamic tools."""
         require_dynamic_tools()
         await sdk._ensure_initialized()
         raw = {key: value for key, value in params.items() if value is not None}
         # Translate Python snake_case to Codex App Server camelCase wire protocol
         if "developer_instructions" in raw:
             raw["developerInstructions"] = raw.pop("developer_instructions")
         raw["dynamicTools"] = list(dynamic_tool_specs(dynamic_tools))
         response = await sdk._client.thread_start(raw)
         from openai_codex import AsyncThread

         return AsyncThread(sdk, _thread_id(response))
     ```
   - **Invariants**:
     - Python code uses `developer_instructions` (snake_case) exclusively.
     - The wire protocol receives `developerInstructions` (camelCase) exclusively.
     - Provider base instructions (`baseInstructions`) are never replaced, cleared, or overwritten.
     - Core Proteo contracts and `RuntimeTask` maintain zero knowledge of camelCase wire fields.
3. **Not Resent by Caller**: Subsequent calls to `task.ainvoke(...)` supply only the new user turn.
4. **Not Host Conversation State**: Instructions do not appear in caller-side history replays and are not stored in host business state.
5. **No Per-Turn Mutation API**: `InvocationConfig` intentionally does NOT declare an `instructions` field, precluding mid-task mutation.

### 4.3 Provider-Neutral `ToolRequest` Extension & Multiplexer Routing

To correlate tool execution events directly to `RuntimeTask` without exposing raw provider thread IDs or conflating ephemeral tasks with durable sessions, `ToolRequest` is extended with an optional `task_id` in `src/proteo_runtime/tools/__init__.py`:

```python
@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Immutable request received from a provider adapter."""

    invocation_id: str
    call_id: str
    name: str
    arguments: Mapping[str, Any]
    session_id: str | None = None
    turn_id: str | None = None
    task_id: str | None = None  # Provider-neutral task correlation
```

#### Routing & Event Correlation Mechanics:
1. **`RuntimeTask` Execution**:
   - `CodexToolBridge` (in `src/proteo_runtime/providers/codex/experimental.py`) sets `ToolRequest.task_id = task.id`.
   - `ToolRequest.session_id = None` (raw provider thread IDs are never assigned to `session_id` or `task_id`).
   - `ToolRequest.turn_id = current_turn_id`.
   - `ToolRequest.invocation_id = current_invocation_id`.
2. **`RuntimeSession` Execution**:
   - `ToolRequest.task_id = None`.
   - `ToolRequest.session_id = session_identity` (conforming to the existing persistent session contract).
3. **`ToolExecutor` Event Emission Path**:
   - The `ToolExecutor` event emission path (implemented via the internal `_emit(...)` helper in `src/proteo_runtime/tools/__init__.py`) must propagate `request.task_id -> RuntimeEvent.task_id` across all emitted tool lifecycle events (`TOOL_REQUESTED`, `TOOL_STARTED`, `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_DENIED`, and retries):
     ```python
     event = RuntimeEvent(
         kind=kind,
         event_id=f"{request.invocation_id}:{self._sequence}",
         sequence=self._sequence,
         occurred_at=datetime.now(UTC),
         runtime=RuntimeIdentity("proteo-runtime", "host-tools"),
         invocation_id=request.invocation_id,
         session_id=request.session_id,
         turn_id=request.turn_id,
         task_id=request.task_id,  # Propagated from ToolRequest
         metadata=...,
         payload=...,
     )
     ```
   - *Design Invariant*: This requirement is functional and behavior-oriented. It mandates observable telemetry propagation across all tool lifecycle events without depending on internal private naming conventions or introducing non-existent methods such as `_emit_event()`.
4. **Multiplexer Routing (`CodexToolMux`)**:
   - For every active turn in a `controlled_agent` task, dynamic tools are bound into the multiplexer (`CodexToolMux` in `src/proteo_runtime/providers/codex/experimental.py`) matching `(thread_id, turn_id)`.
   - Incoming provider tool requests are dispatched to the matching `CodexToolBridge` (`src/proteo_runtime/providers/codex/experimental.py`).
   - Any request for an unregistered or unknown multiplexer route fails closed immediately without tool execution.

### 4.4 Identifier Semantics & `ToolExecutor.end_invocation` Contract

Proteo enforces a strict semantic separation across identifiers (with core tool contracts defined in `src/proteo_runtime/tools/__init__.py`):
- `task_id`: Stable throughout the lifetime of `RuntimeTask`. Correlates all task events and telemetry.
- `turn_id`: Identifies an individual conversational turn within the task.
- `invocation_id`: Identifies an individual provider/tool execution attempt. Serves as the unique key used by `ToolExecutor` for execution deduplication and cleanup.

`ToolExecutor.end_invocation()` contractually and exclusively takes `invocation_id` as its argument:
```python
class ToolExecutor:
    async def end_invocation(self, invocation_id: str) -> None:
        """Clean up tool execution state and deduplication tracking for an invocation."""
```

Rules:
1. At the conclusion or failure of every individual turn, the runtime calls:
   ```python
   await executor.end_invocation(invocation_id)
   ```
2. If a turn is active during task teardown (`RuntimeTask.close()`), the runtime calls:
   ```python
   await executor.end_invocation(active_invocation_id)
   ```
3. `turn_id` must NEVER be passed as an argument to `end_invocation()`.

---

## 5. In-Memory Active Task Registry & Resolution

The runtime instance owns the active in-memory task registry:

```python
class CodexRuntime:
    def __init__(self, ...):
        self._tasks: dict[str, RuntimeTask[Any]] = {}

    async def task(
        self,
        profile: str = "controlled_agent",
        *,
        level: str = "medium",
        instructions: str | None = None,
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeTask[Any]:
        # Capabilities, profile boundary, and mandatory tool binding checks...
        task_id = f"task_{uuid.uuid4().hex}"
        task = _CodexTask(
            id=task_id,
            runtime=self,
            instructions=instructions,
            tool_snapshot=tool_snapshot,
            tool_executor=tool_executor,
            ...
        )
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> RuntimeTask[Any]:
        task = self._tasks.get(task_id)
        if task is None:
            raise SessionNotFoundError(f"Task '{task_id}' not found or already closed")
        return task

    async def close(self) -> None:
        # Cascade close to all active tasks
        open_tasks = list(self._tasks.values())
        for task in open_tasks:
            try:
                await task.close()
            except Exception:
                logger.warning("Error closing task %s during runtime shutdown", task.id)
        self._tasks.clear()
```

### Registry Lifecycle & Routing Invariants:
1. **Generation**: `task_id` is generated by Proteo (`f"task_{uuid.uuid4().hex}"`), opaque, unique per runtime instance, and never includes raw provider thread IDs.
2. **Registration**: Added to `runtime._tasks` on creation.
3. **Unregistration**: Removed from `runtime._tasks` upon `task.close()`.
4. **Resolution**: Callers resolve via `runtime.get_task(task_id)`.
5. **Unknown / Closed ID**: Raises `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
6. **Process Restart**: Memory is cleared; lookups after process restart raise `SessionNotFoundError`.
7. **Mutual Exclusion in Integrations**:
   In `RuntimeNode` (LangGraph):
   ```python
   task_id = config.get("configurable", {}).get("proteo_task_id")
   session_id = config.get("configurable", {}).get("proteo_session_id")
   if task_id and session_id:
       raise ConfigurationError("Cannot specify both proteo_task_id and proteo_session_id in RunnableConfig")
   ```

### 5.1 Non-Resumability Guard & SessionCodec Protection in `resume_session()`

A `task_id` generated by Proteo is an ephemeral task handle conforming to the reserved namespace `task_<opaque-id>` and is **not** a `SessionDescriptor`. It must never enter `SessionCodec.decode()`.

Both `CodexRuntime` and `FakeRuntime` implement an explicit entry guard at the start of `resume_session()`:

```python
# In CodexRuntime.resume_session(self, descriptor: str, ...)
if not isinstance(descriptor, str):
    raise TypeError("Session descriptor must be a string")

# Explicit non-resumability guard before SessionCodec
if descriptor.startswith("task_"):
    raise SessionNotFoundError(
        f"Task '{descriptor}' is ephemeral and cannot be resumed as a session"
    )

raw = descriptor
decoded = SessionCodec.decode(raw)
...
```

```python
# In FakeRuntime.resume_session(self, session_id: str, ...)
if not isinstance(session_id, str):
    raise TypeError("Session descriptor must be a string")

# Explicit non-resumability guard before SessionCodec
if session_id.startswith("task_"):
    raise SessionNotFoundError(
        f"Task '{session_id}' is ephemeral and cannot be resumed as a session"
    )

if session_id in self._deleted_sessions:
    raise SessionNotFoundError("Fake session was not found")

descriptor = SessionCodec.decode(session_id)
...
```

#### Guard Invariants:
1. **Reserved Namespace**: Any identifier starting with `task_` is recognized as an ephemeral task ID.
2. **Pre-Codec Evaluation**: The check executes before `SessionCodec.decode()`, ensuring attempts to resume tasks fail with `SessionNotFoundError` reflecting lifecycle semantics rather than `SessionMismatchError` or descriptor syntax errors.
3. **Deterministic Error Message**: Both runtimes raise `SessionNotFoundError(f"Task '{identifier}' is ephemeral and cannot be resumed as a session")`.
4. **Standard Session Passthrough**: Values not beginning with `task_` proceed directly to normal `SessionCodec` decoding without modification.

---

## 6. Semantic Configuration & Authority Freezing

At task creation, the following are permanently frozen:
- Profile name (`"controlled_agent"`)
- Resolved model name and reasoning effort
- Context policy (`ContextPolicy.RUNTIME`)
- Security policy (`SecurityPolicy.CONTROLLED_TOOLS`)
- Task instructions
- Tool registry snapshot (tool schemas and function names)
- Tool executor, permission policy, and approval handler
- Workspace / sandbox path

### Per-Turn `InvocationConfig` Audit:

The real `InvocationConfig` fields are:
`model`, `reasoning_effort`, `include_raw`, `timeout_seconds`, `metadata`.

| `InvocationConfig` Field | Allowed per-turn? | Enforcement / Behavior |
|---|---|---|
| `timeout_seconds` | **Allowed** | Overrides turn timeout for this specific turn. |
| `include_raw` | **Allowed** | Toggles raw provider payload inclusion in `RuntimeResult`. |
| `metadata` | **Allowed** | Merged into turn-level event metadata. |
| `model` | **Prohibited** | Must match frozen model; if different, raises `ConfigurationError`. |
| `reasoning_effort` | **Prohibited** | Must match frozen effort; if different, raises `ConfigurationError`. |

*Note*: `InvocationConfig` does not declare an `instructions` field. Instructions are exclusively set at task initialization on `runtime.task(...)` and exposed via the read-only `RuntimeTask.instructions` property, precluding per-turn mutation.

Validation occurs **before inference begins**. Prohibited overrides are never silently ignored.

---

## 7. Bounded Shared Engine & Hardened Context Replay Protection

To avoid duplicating turn execution logic between `_CodexTask` (ephemeral multi-turn) and `_CodexSession` (durable session), an internal helper `_StatefulContext` is shared.

### Shared Mechanics:
- Single-active-turn lock (`asyncio.Lock`)
- Turn execution flow and prompt formatting
- Hardened Context Replay Protection:
  ```python
  def _validate_input_for_runtime_context(input: str | RuntimeInput) -> None:
      """Enforce user-only input under ContextPolicy.RUNTIME.

      The neutral RuntimeMessage contract only admits Literal["system", "user", "assistant", "tool"].
      The 'developer' identifier is NOT a message role; developer-level instructions are task-scoped
      and configured exclusively via runtime.task(instructions=...).
      Valid RuntimeMessage instances with role 'system', 'assistant', or 'tool' are rejected before inference.
      """
      if isinstance(input, str):
          return  # Plain string is implicitly a single user turn
      for message in input.messages:
          if message.role != "user":
              raise ContextPolicyError(
                  f"Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; "
                  f"replaying '{message.role}' messages or injecting non-user turns is prohibited."
              )
  ```
- Event streaming plumbing and turn event generation
- Dynamic tool bridge per-turn dispatch
- Timeout and cancellation plumbing
- Per-turn `ToolExecutor.end_invocation(invocation_id)` cleanup

### Strictly Excluded from Shared Engine:
- `SessionDescriptor` generation and parsing
- Persistence, resume, and serialization
- `archive()` and `delete()` methods
- Session migration (`migrate_session`)
- In-memory task registry operations
- Ephemeral workspace directory deletion
- Ephemeral provider thread deletion

---

## 8. Exact `RuntimeTask.close()` Semantics & Teardown Flow

`RuntimeTask` enforces an explicit three-state lifecycle machine to eliminate races between teardown and incoming turns:

```text
Task Lifecycle State Machine:
  [ OPEN ]
     │
     │ close() called
     ▼
  [ CLOSING ] ──► Any incoming ainvoke()/astream()/interrupt() raises SessionNotFoundError
     │
     │ Teardown & cleanup executed (single execution)
     ▼
  [ CLOSED ] ──► Any incoming call raises SessionNotFoundError; subsequent close() returns None
```

### Invariants:
1. **State Machine (`OPEN -> CLOSING -> CLOSED`)**:
   - `OPEN`: Task accepts turns and tool execution.
   - `CLOSING`: Teardown has begun. Any call to `ainvoke()`, `astream()`, or `interrupt()` fails immediately with `SessionNotFoundError("Task '{task_id}' not found or already closed")` before provider inference, tool execution, or SDK routing.
   - `CLOSED`: Teardown has completed; resources and registry entries are freed. Any invocation fails with `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
2. **Concurrent `close()` Idempotency**:
   - `close()` is strictly idempotent.
   - If `close()` is invoked while the task is already `CLOSED`, it returns `None` immediately.
   - If `close()` is invoked while the task is currently `CLOSING`, the caller awaits the completion of the ongoing teardown (via an internal `asyncio.Event`) and returns `None` without duplicating teardown actions or emitting redundant events.
   - `TASK_CLOSED` is emitted strictly once upon completion of teardown.
3. **Separation of Public `interrupt()` from Internal Teardown Cancellation**:
   - **Public API (`task.interrupt()`)**: Obeys lifecycle state guards. Calling `task.interrupt()` while the task is in `CLOSING` or `CLOSED` state fails immediately with `SessionNotFoundError("Task '{task_id}' not found or already closed")`.
   - **Internal Teardown Primitive**: `task.close()` owns teardown and does NOT invoke public `task.interrupt()`. Instead, `close()` directly triggers the internal provider/run cancellation primitive (conceptually `await active_run.interrupt()` or the internal runner cancellation mechanism).
   - This eliminates any self-conflict where `close()` would otherwise block against its own `CLOSING` state guard.
   - The internal cancellation primitive is never exposed as a new public API.

### Step-by-Step Teardown Flow:
```text
1. Check state:
   - If self._state == TaskState.CLOSED -> return None immediately.
   - If self._state == TaskState.CLOSING -> await self._close_event.wait(); return None.
2. Transition state: self._state = TaskState.CLOSING.
   (From this instant, any concurrent or new ainvoke/astream/interrupt fails with SessionNotFoundError).
3. If a turn is currently active:
   a. Request cancellation on active turn directly via internal cancellation primitive (e.g. await active_run.interrupt(); close() does not invoke public task.interrupt()).
   b. Await active turn completion with bounded grace period (default: 5.0 seconds).
   c. If grace period expires, invalidate provider thread handle.
4. Unregister tool bridge routes from SDK multiplexer.
5. If turn was active, invoke ToolExecutor.end_invocation(active_invocation_id).
6. Release/destroy provider task context where supported (call SDK ephemeral thread release/delete).
7. Remove temporary workspace directory from filesystem.
8. Remove task from runtime active registry: runtime._tasks.pop(self.id, None).
9. Transition state: self._state = TaskState.CLOSED; self._close_event.set().
10. Emit TASK_CLOSED runtime event (strictly once).
```

### Cleanup Failure Resilience:
- Each cleanup step (steps 4 through 8) is wrapped in a try/except block.
- If an individual step fails (e.g., filesystem deletion locked on Windows or network timeout releasing thread), the failure is logged as a diagnostic observability event.
- Teardown continues best-effort through remaining steps.
- The task handle remains marked closed (`self._state = TaskState.CLOSED`) and unusable.
- The task is NEVER reopened.
- `TASK_CLOSED` is emitted exactly once.

---

## 9. Deterministic Error Taxonomy

Zero ambiguity or alternatives exist in the error model. The runtime reuses established Proteo error types:

| Situation | Exact Exception | Stable Code | Detail / Message Pattern |
|---|---|---|---|
| Concurrent turn on active task | `SessionBusyError` | `session_busy` | `"Task already has an active turn"` |
| Unknown or closed `task_id` | `SessionNotFoundError` | `session_not_found` | `"Task '{task_id}' not found or already closed"` |
| Operations on closing or closed task handle | `SessionNotFoundError` | `session_not_found` | `"Task '{task_id}' not found or already closed"` |
| Resuming ephemeral task | `SessionNotFoundError` | `session_not_found` | `"Task '{task_id}' is ephemeral and cannot be resumed as a session"` |
| Factory boundary mismatch | `CapabilityError` | `capability_error` | Prescriptive message explaining required factory |
| Missing runtime capability | `CapabilityError` | `capability_error` | `"Runtime '{name}' does not support ephemeral_tasks"` |
| Missing/invalid tool bindings on task | `CapabilityError` | `capability_error` | `"A host-tool registry is required for this profile"` |
| Prohibited turn config override | `ConfigurationError` | `configuration_error` | `"Cannot override frozen property '{key}' on active task"` |
| Conflicting integration IDs | `ConfigurationError` | `configuration_error` | `"Cannot specify both proteo_task_id and proteo_session_id"` |
| Non-user role / context replay attempt | `ContextPolicyError` | `context_policy_error` | `"Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'..."` |
| Tool denied by policy | `ToolDeniedError` | `tool_denied` | Standard tool denial diagnostics |
| Explicit interruption | `InterruptedError` | `interrupted` | Standard interruption code |

---

## 10. Observability & Telemetry Architecture

All telemetry originating within a task correlates via `task_id`:

```text
Task Lifecycle:
  TASK_STARTED(task_id="task_abc", profile="controlled_agent", model="...")
    Turn 1:
      INVOCATION_STARTED(task_id="task_abc", turn_id="turn_1")
      TOOL_REQUESTED(task_id="task_abc", turn_id="turn_1", tool="lookup")
      TOOL_STARTED(task_id="task_abc", turn_id="turn_1", tool="lookup")
      TOOL_COMPLETED(task_id="task_abc", turn_id="turn_1", tool="lookup")
      INVOCATION_COMPLETED(task_id="task_abc", turn_id="turn_1")
    Turn 2:
      INVOCATION_STARTED(task_id="task_abc", turn_id="turn_2")
      INVOCATION_COMPLETED(task_id="task_abc", turn_id="turn_2")
  TASK_CLOSED(task_id="task_abc")
```

### Telemetry Attributes & Module Boundaries:
- `RuntimeEvent.task_id`, `TASK_STARTED`, `TASK_CLOSED`: Defined in `src/proteo_runtime/core/events.py`.
- `RuntimeResult.task_id`: Defined in `src/proteo_runtime/core/model.py`.
- `ToolRequest.task_id`: Defined in `src/proteo_runtime/tools/__init__.py`. The `ToolExecutor` event emission path (in `src/proteo_runtime/tools/__init__.py` via `_emit(...)`) propagates `request.task_id -> RuntimeEvent.task_id` for all tool lifecycle events.
- `task_id`: Stable throughout task life and tool executions.
- `turn_id` / `invocation_id`: Unique per turn.
- `session_id`: Strictly `None` for tasks and their associated tool requests/events.
- OpenTelemetry Spans: Attribute `proteo.task_id = "task_abc"`. Low-cardinality metric labels do NOT contain `task_id`.
- LangSmith Metadata: Projected as `metadata["proteo_task_id"] = "task_abc"`.
- Data Privacy: Raw provider thread IDs are NEVER emitted in events, traces, or metadata.

---

## 11. Live Codex Integration & Authentication

Integration testing against real Codex App Server:
- **Authentication**: Uses managed Codex subscription credentials via Codex App Server and CLI login (`codex login`).
- **Pre-flight Check**: Pre-flight check executes `await runtime.start()`. If missing or invalid authentication, `start()` raises `AuthenticationError`, which the test catches and converts to `pytest.skip("Codex subscription login is not active; skipping live integration tests.")`.
- **Zero API Keys**: Does NOT require or accept `OPENAI_API_KEY`.
- **Opt-in Gate**: Requires environment variable `PROTEO_CODEX_INTEGRATION=1` and pytest marker `-m integration`.
