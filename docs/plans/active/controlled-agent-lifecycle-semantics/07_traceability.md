# Traceability Matrix — Controlled Agent Lifecycle Semantics

## 1. Full Bidirectional Traceability Matrix

| Requirement ID | Project Guide § | Task ID(s) | Acceptance Criterion | Validation Scenario |
|---|---|---|---|---|
| **CAL-REQ-001** (`controlled_turn`) | §9.5 | `CAL-TASK-0001` | `AC-CAL-001` | `SCEN-001` |
| **CAL-REQ-002** (`controlled_agent`) | §9.4 | `CAL-TASK-0002` | `AC-CAL-002` | `SCEN-002` |
| **CAL-REQ-003** (Profile Specs) | §9.0 | `CAL-TASK-0001`, `CAL-TASK-0002` | `AC-CAL-003` | `SCEN-003` |
| **CAL-REQ-004** (Config Schema) | §9.0 | `CAL-TASK-0003` | `AC-CAL-004` | `SCEN-004` |
| **CAL-REQ-005** (Codex Mappings) | §9.5 | `CAL-TASK-0004` | `AC-CAL-005` | `SCEN-005` |
| **CAL-REQ-006** (Strict Lookup) | §8.1 | `CAL-TASK-0004`, `CAL-TASK-0023` | `AC-CAL-006` | `SCEN-006` |
| **CAL-REQ-007** (`RuntimeTask[T]`) | §7.3 | `CAL-TASK-0005` | `AC-CAL-007` | `SCEN-007` |
| **CAL-REQ-008** (`Runtime.task`) | §7.2 | `CAL-TASK-0006`, `CAL-TASK-0011`, `CAL-TASK-0012` | `AC-CAL-008` | `SCEN-008` |
| **CAL-REQ-008b** (Factory Boundaries) | §7.2 | `CAL-TASK-0009`, `CAL-TASK-0023` | `AC-CAL-008b` | `SCEN-009`, `SCEN-010`, `SCEN-011` |
| **CAL-REQ-008c** (Task Instructions) | §9.4 | `CAL-TASK-0005`, `CAL-TASK-0011`, `CAL-TASK-0012`, `CAL-TASK-0017`, `CAL-TASK-0024` | `AC-CAL-008c` | `SCEN-012`, `SCEN-013` |
| **CAL-REQ-008d** (Task Registry) | §7.3 | `CAL-TASK-0010`, `CAL-TASK-0020`, `CAL-TASK-0024` | `AC-CAL-008d` | `SCEN-014`, `SCEN-015`, `SCEN-016`, `SCEN-017` |
| **CAL-REQ-008e** (Mandatory Tool Bindings) | §11.2 | `CAL-TASK-0009`, `CAL-TASK-0011`, `CAL-TASK-0012`, `CAL-TASK-0024` | `AC-CAL-008e` | `SCEN-008b`, `SCEN-008c`, `SCEN-008d` |
| **CAL-REQ-008f** (Codex Instructions Wire) | §9.5 | `CAL-TASK-0012`, `CAL-TASK-0023` | `AC-CAL-008f` | `SCEN-012b` |
| **CAL-REQ-009** (Non-Resumability) | §7.3 | `CAL-TASK-0005`, `CAL-TASK-0010`, `CAL-TASK-0024` | `AC-CAL-009` | `SCEN-018` |
| **CAL-REQ-010** (Single Active Turn) | §15.1 | `CAL-TASK-0013`, `CAL-TASK-0024` | `AC-CAL-010` | `SCEN-019` |
| **CAL-REQ-010b** (Context Replay Protection) | §10.3 | `CAL-TASK-0005`, `CAL-TASK-0013b`, `CAL-TASK-0024` | `AC-CAL-010b` | `SCEN-019b` |
| **CAL-REQ-011** (Post-Close Invalidation) | §7.3 | `CAL-TASK-0015`, `CAL-TASK-0024` | `AC-CAL-011` | `SCEN-020` |
| **CAL-REQ-011b** (Teardown Race Prevention) | §10.2 | `CAL-TASK-0015`, `CAL-TASK-0024` | `AC-CAL-011b` | `SCEN-023b` |
| **CAL-REQ-012** (Thread Reuse) | §10.2 | `CAL-TASK-0012`, `CAL-TASK-0024` | `AC-CAL-012` | `SCEN-021` |
| **CAL-REQ-013** (Workspace Lifecycle) | §12.3 | `CAL-TASK-0014` | `AC-CAL-013` | `SCEN-022` |
| **CAL-REQ-014** (Teardown Flow) | §10.2 | `CAL-TASK-0015` | `AC-CAL-014` | `SCEN-024` |
| **CAL-REQ-014b** (Idempotent Close) | §10.2 | `CAL-TASK-0015`, `CAL-TASK-0024` | `AC-CAL-014b` | `SCEN-023`, `SCEN-024` |
| **CAL-REQ-015** (Frozen Authority) | §11.2 | `CAL-TASK-0016` | `AC-CAL-015` | `SCEN-025` |
| **CAL-REQ-015b** (Turn Config Validation) | §7.2 | `CAL-TASK-0017`, `CAL-TASK-0024` | `AC-CAL-015b` | `SCEN-026` |
| **CAL-REQ-016** (Turn Identification) | §11.2 | `CAL-TASK-0018` | `AC-CAL-016` | `SCEN-027` |
| **CAL-REQ-017** (`end_invocation`) | §11.2 | `CAL-TASK-0018` | `AC-CAL-017` | `SCEN-028` |
| **CAL-REQ-018** (Mux Registration) | §11.2 | `CAL-TASK-0019`, `CAL-TASK-0024` | `AC-CAL-018` | `SCEN-028b` |
| **CAL-REQ-019** (LangGraph Node) | §16.1 | `CAL-TASK-0020` | `AC-CAL-019` | `SCEN-017` |
| **CAL-REQ-020** (`ephemeral_tasks` Cap) | §13.1 | `CAL-TASK-0007`, `CAL-TASK-0023` | `AC-CAL-020` | `SCEN-029` |
| **CAL-REQ-021** (Observability) | §14.1 | `CAL-TASK-0008`, `CAL-TASK-0021` | `AC-CAL-021` | `SCEN-030` |
| **CAL-REQ-022** (Example Migration) | §18.1 | `CAL-TASK-0022` | `AC-CAL-022` | `SCEN-031` |
| **CAL-REQ-023** (Unit Test Suite) | §15.1 | `CAL-TASK-0023`, `CAL-TASK-0024` | `AC-CAL-023` | `SCEN-001`–`SCEN-030` |
| **CAL-REQ-024** (Live Smoke Test) | §15.1 | `CAL-TASK-0025` | `AC-CAL-024` | `SCEN-032` |
| **CAL-REQ-025** (Design Guide Sync) | §1.0 | `CAL-TASK-0027` | `AC-CAL-025` | `SCEN-001`–`SCEN-032` |
| **CAL-REQ-026** (ADR 0004 Sync) | §1.0 | `CAL-TASK-0026` | `AC-CAL-026` | `SCEN-001`–`SCEN-032` |

---

## 2. Closed Architectural Decisions (Zero Ambiguity / Zero "or")

| Architectural Decision | Chosen Deterministic Policy | Discarded Alternatives | Justification |
|---|---|---|---|
| Mandatory tool bindings for `controlled_agent` | Mandatory `registry`, optional `executor`, explicit entry guard `if registry is None:` before `_tool_binding()` rejecting executor-only calls; default executor constructed if omitted; fail-fast with `CapabilityError` on missing, empty, or mismatched bindings | Permitting executor-only creation without registry, silent fallback, or implicit empty registry | `controlled_agent` profile mandates host-managed tools; starting without explicit tool registry is an invalid configuration; `_tool_binding()` alone would otherwise accept executor without registry. |
| Hardened context replay protection | Accept only `user` role per turn; reject valid `RuntimeMessage` instances with `system`, `assistant`, or `tool` with `ContextPolicyError`; `developer` is not a `RuntimeMessage` role and per-turn developer instructions are prohibited | Allowing transcript replay, per-turn system overrides, or per-turn developer instruction injection | Under `ContextPolicy.RUNTIME`, runtime owns conversational state; host provides only user input; instructions are set exclusively via `runtime.task(instructions=...)`. |
| Calling convention of `runtime.model` | Synchronous `def model(...)` | Asynchronous `async def model(...)` | Aligns with existing Proteo `Runtime` contract; callers invoke `runtime.model(...)` without `await`. |
| Task instructions immutability & mapping | Set at `runtime.task(...)` initialization; read-only property; mapped to Codex `developer_instructions` | Adding `instructions` to `InvocationConfig` or overriding base instructions | Preserves base provider instructions, avoids prompt drift, and maintains clean invocation configuration. |
| Codex task instructions wire translation | Python caller uses snake_case `developer_instructions`; compatibility bridge translates to camelCase `developerInstructions` in raw request; `baseInstructions` remains untouched; zero camelCase leak to core | Exposing camelCase `developerInstructions` to Python code or passing untranslated snake_case over wire | Preserves Python PEP 8 conventions internally while correctly satisfying Codex App Server JSON-RPC wire protocol requirements. |
| Observability module boundaries | `RuntimeEvent.task_id` in `events.py`; `RuntimeResult.task_id` in `model.py`; `ToolRequest.task_id` in `tools/__init__.py` | Consolidating in one file or creating circular imports | Respects existing Proteo core module organization without arbitrary code movement. |
| ToolRequest task_id & tool event correlation | Additive provider-neutral field `ToolRequest.task_id` (populated with `task.id` on task turns; `session_id=None`); `ToolExecutor` event emission path propagates `request.task_id -> RuntimeEvent.task_id` across all tool events (via `_emit(...)`) | Overloading `session_id` with `task_id` or raw provider thread IDs | Preserves clean distinction between ephemeral tasks and durable sessions while ensuring complete event correlation without raw provider thread leaks. |
| Asynchronous capability check | `await self.capabilities()` | Synchronous property access `self.capabilities` | Conforms strictly to the `Runtime.capabilities()` async protocol contract. |
| Concurrent turn error | `SessionBusyError` | `TaskBusyError` or generic `RuntimeError` | Reuses existing Proteo error taxonomy cleanly without creating redundant exception types. |
| Closed or missing task error | `SessionNotFoundError` | `LifecycleError` or `TaskNotFoundError` | Reuses established identifier lookup failure semantics across all stateful handles. |
| Non-resumability guard for ephemeral tasks | Explicit entry guard in `resume_session()` detecting reserved `task_` prefix before `SessionCodec.decode()`, raising `SessionNotFoundError("Task '<task_id>' is ephemeral and cannot be resumed as a session")` | Passing `task_id` to `SessionCodec.decode()`, failing with descriptor syntax errors or `SessionMismatchError` | Enforces lifecycle semantics fail-fast at API entry; `task_id` is an ephemeral handle, not a `SessionDescriptor`, and must never enter codec decoding. |
| Teardown state machine & race prevention | Strict `OPEN -> CLOSING -> CLOSED` state machine; immediate rejection of new turns in `CLOSING` state with `SessionNotFoundError("Task '<task_id>' not found or already closed")`; concurrent `close()` calls do not duplicate cleanup or events | Allowing new turns during `_closing` window, raising concurrency conflict `SessionBusyError`, or silently dropping turns | Eliminates race conditions where turns could start while tools, workspaces, or provider contexts are being torn down; maintains symmetric error with `CLOSED` state. |
| Incompatible profile error | `CapabilityError` | `ValueError` or silent degradation | Enforces fail-fast boundary invariants without silent memory retention. |
| Prohibited turn config override | `ConfigurationError` | Silent ignore or fallback | Prevents authority expansion or semantic confusion before inference begins. |
| Multi-turn ephemeral capability advertising | Dataclass default `ephemeral_tasks=False`; `CodexRuntime` advertises `True` when supported; `FakeRuntime` advertises `True` by default; non-supporting runtimes retain `False` | Overloading `ephemeral_sessions` or leaving default `False` on supporting runtimes | Disentangles one-shot ephemeral thread support from multi-turn tasks while ensuring supporting runtimes explicitly enable `RuntimeTask` without self-rejection. |
| Task registry ownership | Owned by `Runtime` instance (`_tasks`) | Global process dictionary or durable database | Respects in-memory, process-bound lifecycle of ephemeral tasks. |
| Task close idempotence | Safe no-op returning `None` | Raising exception on second close | Standard Python resource manager semantics; safe for multiple teardown callers. |
| Smoke test authentication | Codex subscription via `CodexRuntime.start()` pre-flight | `$env:OPENAI_API_KEY="sk-..."` or invented SDK APIs | Strictly aligns with subscription-backed Codex App Server design authority, skipping cleanly if unauthenticated. |
| Smart Quote Agent migration | Migrate `app.py`, `graph.py`, `README.md`, `tests/` to `controlled_turn` | Migrating full multi-turn domain or leaving on deprecated profile | Preserves invocation-scoped tool reasoning without introducing unnecessary task lifecycle overhead. |
| ADR 0004 governance | Validate and synchronize existing ADR via `CAL-TASK-0026` | Re-authoring or recreating ADR | ADR 0004 is already accepted; governance requires synchronization rather than duplication. |
| `ToolExecutor.end_invocation` contract | Strictly receives `invocation_id` (`ToolExecutor.end_invocation(invocation_id)`, and `ToolExecutor.end_invocation(active_invocation_id)` during teardown) | Passing `turn_id` or `active_turn_id` | `turn_id` identifies a conversational turn, whereas `invocation_id` identifies a specific provider/tool execution attempt and is the unique key used by `ToolExecutor` for deduplication and cleanup. |
| Teardown active turn cancellation | `close()` cancels active turns directly via internal cancellation primitive (e.g. `await active_run.interrupt()`); public `task.interrupt()` adheres strictly to state machine and is rejected with `SessionNotFoundError` in `CLOSING`/`CLOSED` | Having `close()` call public `task.interrupt()` or exposing internal primitive publicly | Eliminates self-conflict where `close()` would block against its own `CLOSING` state guard; keeps provider cancellation internal. |

---

## 3. Completeness Verification

- **Total Requirements**: 35 (`CAL-REQ-001` through `CAL-REQ-026`, including `CAL-REQ-008b/c/d/e/f`, `CAL-REQ-010b`, `CAL-REQ-011b`, `CAL-REQ-014b`, `CAL-REQ-015b`).
- **Total Tasks**: 28 (`CAL-TASK-0001` through `CAL-TASK-0027`, including `CAL-TASK-0013b`). All tasks are in `pending` status.
- **Total Acceptance Criteria**: 35 (`AC-CAL-001` through `AC-CAL-026`, including `AC-CAL-008b/c/d/e/f`, `AC-CAL-010b`, `AC-CAL-011b`, `AC-CAL-014b`, `AC-CAL-015b`).
- **Total Validation Scenarios**: 39 (`SCEN-001` through `SCEN-032`, including `SCEN-008b/c/d`, `SCEN-012b`, `SCEN-019b`, `SCEN-023b`, `SCEN-028b`).
- **Orphaned IDs**: 0. Every ID across all categories is linked bidirectionally.
