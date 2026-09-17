# Validation Plan — Controlled Agent Lifecycle Semantics

## 1. Test Execution Commands & Verification Gates

The test plan enforces a strict separation between mandatory offline verification and optional live provider verification.

### 1.1 Mandatory Offline Verification Suite
The complete offline suite must execute and pass without requiring external network access or provider credentials:

```powershell
# 1. Linting & formatting check across codebase, tests, and examples
uv run ruff check src tests examples
uv run ruff format --check src tests examples

# 2. Strict static type analysis
uv run mypy src

# 3. Architecture & import boundaries verification
uv run lint-imports

# 4. Unit test suite for core contracts and controlled profiles
uv run pytest tests/unit -v

# 5. Domain integration suite for Smart Quote Agent example
uv run pytest examples/smart_quote_agent -v
```

### 1.2 Optional Live Provider Verification Suite
Live tests against OpenAI Codex are opt-in and require an active ChatGPT / Codex App Server login (`codex login`):

```powershell
# Enable the opt-in integration test suite
$env:PROTEO_CODEX_INTEGRATION = "1"

# Execute the live multi-turn controlled agent smoke test
# Note: Zero reliance on OPENAI_API_KEY. Pre-flight check uses `await runtime.start()`.
uv run pytest tests/integration/codex/test_codex_controlled_agent.py -m integration -v
```

---

## 2. Validation Scenarios

| Scenario ID | Test Target | Description | Expected Outcome |
|---|---|---|---|
| **SCEN-001** | `test_controlled_profiles.py` | Verify `controlled_turn` profile specification | Has `EPHEMERAL`, `EXTERNAL`, `CONTROLLED`, `CONTROLLED_TOOLS`. |
| **SCEN-002** | `test_controlled_profiles.py` | Verify `controlled_agent` profile specification | Has `EPHEMERAL`, `RUNTIME`, `CONTROLLED`, `CONTROLLED_TOOLS`. |
| **SCEN-003** | `test_controlled_profiles.py` | Verify `profile_spec()` resolution | Both `controlled_turn` and `controlled_agent` resolve. |
| **SCEN-004** | `test_controlled_profiles.py` | Verify `RuntimeConfigV1` validation | Permissive of `EPHEMERAL` + `RUNTIME` combinations. |
| **SCEN-005** | `test_controlled_profiles.py` | Verify `codex_v1.json` mappings | Valid models and effort levels configured for `controlled_turn`. |
| **SCEN-006** | `test_controlled_profiles.py` | Strict profile configuration lookup | `lookup("controlled_turn", ...)` does not alias to `controlled_agent`. |
| **SCEN-007** | `test_controlled_profiles.py` | Verify `RuntimeTask` protocol attributes | Exposes `id`, `instructions` (read-only), `ainvoke`, `astream`, `interrupt`, `close`. |
| **SCEN-008** | `test_controlled_agent.py` | Factory creation with valid tool bindings | Calling `await runtime.task(profile="controlled_agent", registry=registry, executor=executor)` or `executor=None` (constructing default compatible executor) returns active task. |
| **SCEN-008b** | `test_controlled_agent.py` | Factory creation without tool registry | Calling `runtime.task("controlled_agent", registry=None, executor=None)` or `runtime.task("controlled_agent", registry=None, executor=executor)` raises `CapabilityError("A host-tool registry is required...")` via entry guard. |
| **SCEN-008c** | `test_controlled_agent.py` | Factory creation with empty registry | Calling `runtime.task("controlled_agent", registry=empty_reg)` raises `CapabilityError("A host-tool registry must contain...")`. |
| **SCEN-008d** | `test_controlled_agent.py` | Factory creation with mismatched executor | Calling `runtime.task("controlled_agent", registry=valid_registry, executor=mismatched_executor)` raises `CapabilityError("Tool executor does not match...")`. |
| **SCEN-009** | `test_controlled_profiles.py` | Factory boundary: synchronous `model("controlled_agent")` | Calling `runtime.model(profile="controlled_agent")` raises `CapabilityError` immediately. |
| **SCEN-010** | `test_controlled_profiles.py` | Factory boundary: `task("controlled_turn")` | Raises `CapabilityError` indicating external context requires `runtime.model()`. |
| **SCEN-011** | `test_controlled_profiles.py` | Factory boundary: `session("controlled_agent")` | Raises `CapabilityError` indicating ephemeral profile cannot create session. |
| **SCEN-012** | `test_controlled_agent.py` | Task instructions persistence | Instructions provided at task start guide all turns without resending. |
| **SCEN-012b** | `test_host_tools.py` | `start_thread` `developerInstructions` wire translation | Offline bridge test: calling `start_thread(..., developer_instructions="Do X")` passes `{"developerInstructions": "Do X"}` to `_client.thread_start(raw)`, removes `developer_instructions`, and leaves `baseInstructions` intact. |
| **SCEN-013** | `test_controlled_agent.py` | Task instructions immutability | `task.instructions` is read-only; no per-turn mutation API exists. |
| **SCEN-014** | `test_controlled_agent.py` | In-memory task registry resolution | `runtime.get_task(task.id)` returns active instance. |
| **SCEN-015** | `test_controlled_agent.py` | Task registry cleanup on `close()` | Unregisters from registry; subsequent `get_task()` raises `SessionNotFoundError`. |
| **SCEN-016** | `test_controlled_agent.py` | Task registry cleanup on `runtime.close()` | Cascades close to all open tasks, clearing registry. |
| **SCEN-017** | `test_controlled_agent.py` | LangGraph mutual exclusion check | Specifying both `proteo_task_id` and `proteo_session_id` raises `ConfigurationError`. |
| **SCEN-018** | `test_controlled_agent.py` | Ephemeral task non-resumability & pre-codec guard | Verify `resume_session()` behavior: 1. Active task ID (`task_...`) raises `SessionNotFoundError("Task '...' is ephemeral and cannot be resumed as a session")` before `SessionCodec`; 2. Closed task ID raises identical `SessionNotFoundError`; 3. Non-task identifier (not starting with `task_`) proceeds to standard `SessionCodec` decode. |
| **SCEN-019** | `test_controlled_agent.py` | Single-active-turn concurrency lock | Concurrent `ainvoke()` on active task raises `SessionBusyError("Task already has an active turn")`. |
| **SCEN-019b** | `test_controlled_agent.py` | Hardened context replay protection role validation | Verify role enforcement on `RuntimeTask`: 1. `str` -> permitted; 2. `role="user"` -> permitted; 3. `role="system"` -> raises `ContextPolicyError`; 4. `role="assistant"` -> raises `ContextPolicyError`; 5. `role="tool"` -> raises `ContextPolicyError`. |
| **SCEN-020** | `test_controlled_agent.py` | Post-close invalidation | Calling `ainvoke()` on closed task raises `SessionNotFoundError`. |
| **SCEN-021** | `test_controlled_agent.py` | Ephemeral thread reuse across turns | Sequential turns reuse the identical underlying provider thread. |
| **SCEN-022** | `test_controlled_agent.py` | Workspace directory lifecycle | Temporary workspace created on task init, shared across turns, deleted on close. |
| **SCEN-023** | `test_controlled_agent.py` | Idempotent `RuntimeTask.close()` | First call cleans up; second call is a safe no-op returning `None`. |
| **SCEN-023b** | `test_controlled_agent.py` | Teardown race prevention (`CLOSING` state rejection) | While task teardown is underway (`CLOSING` state), a concurrent `ainvoke()` or `astream()` call immediately raises `SessionNotFoundError("Task '...' not found or already closed")` before provider inference; concurrent `close()` calls do not duplicate teardown or emit duplicate `TASK_CLOSED` events. |
| **SCEN-024** | `test_controlled_agent.py` | Close during active turn & internal cancellation | While active turn exists: close() transitions task to CLOSING; external task.interrupt() fails with SessionNotFoundError; close() cancels active turn via internal cancellation primitive, waits grace period, unregisters routes, completes teardown to CLOSED, and emits TASK_CLOSED strictly once. |
| **SCEN-025** | `test_controlled_agent.py` | Frozen tool authority snapshot | Tool schema mutations or additions after task creation are blocked. |
| **SCEN-026** | `test_controlled_agent.py` | Per-turn `InvocationConfig` validation | Timeout override succeeds; model or effort override raises `ConfigurationError`. |
| **SCEN-027** | `test_controlled_agent.py` | Turn invocation identification | Each turn has unique `turn_id` / `invocation_id` with stable `task_id`. |
| **SCEN-028** | `test_controlled_agent.py` | `ToolExecutor.end_invocation(invocation_id)` hook | Given a turn with `invocation_id=X`, when the turn completes or fails (or task closes while turn is active), `ToolExecutor.end_invocation(X)` is called with that `invocation_id`. |
| **SCEN-028b** | `test_controlled_agent.py` | Dynamic tool multiplexer routing & correlation | Provider tool call on active turn routes via CodexToolMux to CodexToolBridge; builds ToolRequest with task_id, invocation_id, turn_id, session_id=None; ToolExecutor executes tool and emits TOOL_REQUESTED/STARTED/COMPLETED with matching task_id; unknown mux routes fail closed. |
| **SCEN-029** | `test_controlled_profiles.py` | `ephemeral_tasks` advertising & rejection | 1. `CodexRuntime.capabilities()` advertises `ephemeral_tasks=True` when supported; 2. `FakeRuntime.capabilities()` advertises `ephemeral_tasks=True` by default; 3. Runtime configured with `ephemeral_tasks=False` rejects `runtime.task(profile="controlled_agent", ...)` with `CapabilityError`. |
| **SCEN-030** | `test_controlled_agent.py` | Telemetry correlation | `task_id` attached to spans, events (`events.py`), results (`model.py`), and LangSmith metadata; no raw thread ID leak. |
| **SCEN-031** | `examples/smart_quote_agent` | Smart Quote Agent example migration | Migrated to `controlled_turn` in `app.py`, `graph.py`, `README.md`, passes tests. |
| **SCEN-032** | `test_codex_controlled_agent.py` | Live Codex multi-turn smoke test | Pre-flight check via `CodexRuntime.start()` skips if unauthenticated; verifies turn reuse with tools and clean slate on second task without `OPENAI_API_KEY`. |
