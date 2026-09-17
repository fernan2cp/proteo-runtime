# Rollout & Rollback Plan — Controlled Agent Lifecycle Semantics

## 1. Phased Rollout Sequence

The rollout is structured into six discrete, verifiable phases:

```text
Phase 1: Core Contracts & Capabilities
         ↓
Phase 2: Provider Implementations & Task Registry
         ↓
Phase 3: Semantic Configuration Freezing & Tool Lifecycle
         ↓
Phase 4: Integrations & Observability Propagation
         ↓
Phase 5: Example Migration & Automated Testing
         ↓
Phase 6: Documentation & ADR 0004 Synchronization
```

### Phase 1: Core Contracts & Capabilities
- **Deliverables**:
  - Add `controlled_turn` and update `controlled_agent` in `src/proteo_runtime/core/profiles.py`.
  - Add `ephemeral_tasks: bool = False` to `src/proteo_runtime/core/capabilities.py`.
  - Update `CodexRuntime.capabilities()` to advertise `ephemeral_tasks=True` when provider capabilities are active, and `FakeRuntime` default `_capabilities` to `ephemeral_tasks=True`.
  - Update `RuntimeConfigV1` validation in `src/proteo_runtime/config/models.py`.
  - Add default Codex mappings for `controlled_turn` in `src/proteo_runtime/config/defaults/codex_v1.json`.
  - Create `RuntimeTask[T]` protocol in `src/proteo_runtime/core/task.py` with `input: str | RuntimeInput` and read-only `instructions`.
  - Add `task()` and `get_task()` signatures to `Runtime` in `src/proteo_runtime/core/runtime.py`.
  - Add `TASK_STARTED`, `TASK_CLOSED`, and `task_id` attribute to `src/proteo_runtime/core/events.py`, and `task_id` to `RuntimeResult` in `src/proteo_runtime/core/model.py`.
- **Verification**: `uv run ruff check src` and `uv run mypy src`.

### Phase 2: Provider Implementations & Task Registry
- **Deliverables**:
  - Implement factory lifecycle boundaries in `CodexRuntime` and `FakeRuntime` (rejecting synchronous `runtime.model(profile="controlled_agent")` and `runtime.task(...)` when `ephemeral_tasks=False` with `CapabilityError`).
  - Implement mandatory tool binding validation for `controlled_agent` in `runtime.task(...)` via an explicit entry guard `if registry is None: raise CapabilityError(...)` before delegating to `_tool_binding()` (mandatory registry, optional executor, default executor construction, empty registry rejection, and mismatched executor rejection).
  - Implement active in-memory task registry `_tasks` and non-resumability entry guard in `resume_session()` for `CodexRuntime` and `FakeRuntime` (rejecting identifiers starting with `task_` with `SessionNotFoundError` before reaching `SessionCodec.decode()`).
  - Implement `task(..., instructions=...)` in `FakeRuntime` and `CodexRuntime` (mapping instructions to `developer_instructions` in Python, with `experimental.start_thread()` translating `developer_instructions -> developerInstructions` on the raw App Server wire protocol while leaving `baseInstructions` intact).
  - Implement hardened context replay protection in `_StatefulContext` / `RuntimeTask` (`ContextPolicyError` for non-`user` messages).
  - Implement temporary workspace lifecycle in `CodexRuntime`.
  - Implement explicit lifecycle state machine (`OPEN -> CLOSING -> CLOSED`), teardown race prevention (immediate rejection of new turns in `CLOSING` state with `SessionNotFoundError`), and idempotent `close()` emitting `TASK_CLOSED` strictly once.
- **Verification**: `uv run pytest tests/unit/core/test_controlled_profiles.py`.

### Phase 3: Semantic Configuration Freezing & Tool Lifecycle
- **Deliverables**:
  - Freeze profile, model, effort, instructions, tool registry snapshot, and security policy at task start.
  - Implement per-turn `InvocationConfig` validation in `RuntimeTask.ainvoke()` and `astream()` (rejecting prohibited overrides with `ConfigurationError`).
  - Implement per-turn `invocation_id` routing and `ToolExecutor.end_invocation(invocation_id)` cleanup hook.
  - Bind dynamic tools into Codex SDK mux for task turns.
- **Verification**: `uv run pytest tests/unit/tools/test_controlled_agent.py`.

### Phase 4: Integrations & Observability Propagation
- **Deliverables**:
  - Support `proteo_task_id` routing in `RuntimeNode`.
  - Enforce mutual exclusion between `proteo_task_id` and `proteo_session_id` (`ConfigurationError`).
  - Propagate `task_id` to OpenTelemetry spans, LangSmith metadata, and turn events without leaking raw thread IDs.
- **Verification**: `uv run pytest tests/unit/integrations/langgraph/`.

### Phase 5: Example Migration & Automated Testing
- **Deliverables**:
  - Migrate `examples/smart_quote_agent/` (`app.py`, `graph.py`, `README.md`, `tests/test_agent.py`) to `profile="controlled_turn"`.
  - Implement comprehensive unit test suite in `tests/unit/core/` and `tests/unit/tools/`.
  - Implement live multi-turn smoke test in `tests/integration/codex/test_codex_controlled_agent.py`.
- **Verification**: Mandatory offline test suite passes; live integration test passes under subscription authentication (`codex login`).

### Phase 6: Documentation & ADR 0004 Synchronization
- **Deliverables**:
  - Validate and synchronize `docs/adr/0004-ephemeral-task-context-and-controlled-execution-profiles.md`.
  - Synchronize `docs/design/project-guide.md`.
- **Verification**: Git diff review against architectural requirements.

---

## 2. Blast Radius & Migration Guidance

### 2.1 Direct Callers of `runtime.model(profile="controlled_agent")`
- **Impact**: Calling `runtime.model(profile="controlled_agent")` now raises `CapabilityError` immediately at factory call time.
- **Rationale**: Prevents accidental cross-turn memory leakage in models and avoids silent degradation.
- **Prescriptive Migration**:
  - If single-turn execution with clean external context is required:
    ```python
    # Before:
    model = runtime.model(profile="controlled_agent", level="medium")
    # After:
    model = runtime.model(profile="controlled_turn", level="medium")
    ```
  - If multi-turn execution with runtime context reuse and host tools is required:
    ```python
    # Before (flawed assumption of multi-turn model):
    model = runtime.model(profile="controlled_agent", level="medium")
    # After:
    async with await runtime.task(
        profile="controlled_agent",
        level="medium",
        instructions="...",
        registry=registry,
        executor=executor,
    ) as task:
        res1 = await task.ainvoke("Step 1")
        res2 = await task.ainvoke("Step 2")
    ```

### 2.2 Turn Configuration Overrides
- **Impact**: Callers attempting to change `model` or `reasoning_effort` via `InvocationConfig` on an active `RuntimeTask` will now receive `ConfigurationError`.
- **Prescriptive Migration**: Set configuration and instructions at task creation; only override `timeout_seconds`, `include_raw`, or `metadata` per turn.

### 2.3 LangGraph Configuration
- **Impact**: Passing both `proteo_task_id` and `proteo_session_id` in `RunnableConfig` now raises `ConfigurationError`.
- **Prescriptive Migration**: Pass exclusively one ID depending on whether execution is task-scoped ephemeral or session-scoped persistent.

---

## 3. Rollback Strategies

1. **Clean Git Reversion**: All changes are organized by clean, focused commits. Any phase can be reverted via `git revert` without leaving orphaned data files.
2. **Independent Capabilities**: Because `ephemeral_tasks` is an independent capability flag, `CodexRuntime` and `FakeRuntime` explicitly advertise `ephemeral_tasks=True` when supported, while provider runtimes without task-scoped context support retain `ephemeral_tasks=False` without breaking `controlled_turn`.
3. **No Migration Scripts Required**: Ephemeral tasks have no persistent database records or serialized descriptors, making rollback completely free of data migration hazards.
