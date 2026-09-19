# Rollout and Rollback — Smart Quote Agent Example

## Rollout Strategy

The Smart Quote Agent implementation and conversational hardening progress through six ordered stages. The package stays active until all evidence and human review are complete:

### Stage 1: Directory Scaffolding & Boundary Confirmation
- Establish `examples/smart_quote_agent/data/.gitkeep`.
- Verify git status to confirm that no existing repository files or configurations are altered.

### Stage 2: Domain Logic & SQLite Provisioning
- Implement and verify `database.py`, `init_demo.py`, and `models.py`.
- Run `--reset` provisioning to ensure deterministic schema and seed data.
- Run headless assertions on price calculations, discount math, and transactional persistence.

### Stage 3: Workflow, Tool & CLI Integration
- Implement `auth.py`, `tools.py`, `hitl.py`, `graph.py`, and `app.py`.
- Wire LangGraph routing, host-managed tools, HITL prompts, and console observability.

### Stage 4: Static Analysis & End-to-End Verification
- Execute `uv run mypy examples/smart_quote_agent --strict`.
- Execute `uv run ruff check examples/smart_quote_agent` and `uv run ruff format --check examples/smart_quote_agent`.
- Run the interactive demonstration script and document evidence in `05_validation_plan.md`.

### Stage 5: Conversational Hardening and Task/Workflow Observability
- Keep quote workflow state and revision guards host-owned.
- Validate interruptions, corrections, ambiguity, terminal cleanup, bounded customer access, and local task/workflow inspection using provider-free tests.
- Run the live transcript only if the documented integration opt-in and credentials are available; do not reset or mutate the user's business database.

### Stage 6: Correlated Turn Error Diagnostics
- Create `interaction_id` before graph execution and propagate only safe correlation metadata through existing `InvocationConfig.metadata`.
- Migrate the local observability `runtime_events` table additively with nullable `interaction_id` and an index; do not alter `demo.sqlite3` or runtime APIs.
- Record bounded, redacted `host.turn_error` details and expose runtime/host events with `inspect_observability.py --interaction <id>`.
- Run the requested live transcript. Approve persistence only after exact review values; if the provider fails first, inspect the interaction and confirm the business quote count is unchanged.

### Stage 7: Documentation and Mandatory Human Review Gate
- Complete `examples/smart_quote_agent/README.md` and this active SDD's validation evidence.
- Present the verified implementation to the repository owner, including any live-provider blocker and sanitized diagnostics.
- Keep the SDD active unless/until the owner explicitly approves closure; only then move it to `docs/plans/complete/example-smart-quote-agent/`.

---

## Blast-Radius Analysis

| Scope Area | Impact Assessment | Mitigation & Guarantee |
|---|---|---|
| Core Runtime (`src/`) | **Zero Impact** | No core library files are modified or imported dynamically. |
| Existing Tests (`tests/`) | **Zero Impact** | Existing unit, integration, and quota-safety suites remain untouched. |
| Package Metadata (`pyproject.toml`, `uv.lock`) | **Zero Impact** | No new external dependencies are added; the example relies strictly on existing runtime dependencies (`langgraph`, `pydantic`, `sqlite3`). |
| Working Tree | **Strictly Bounded** | Product/example changes stay within `examples/smart_quote_agent/*`; the only permitted documentation exception is this active SDD package. Pre-existing user modifications are preserved and reported separately. |
| Observability DB | **Additive Local Change** | Only the local observability DB schema may add nullable `task_id` and `interaction_id`; the business `demo.sqlite3` schema remains unchanged. |

---

## Verification Gates

Before presenting the work for final approval and moving the SDD to `complete`:

- [ ] Strict type checking passes (`uv run mypy examples/smart_quote_agent --strict`).
- [ ] Linting and formatting checks pass (`uv run ruff check`, `uv run ruff format --check`).
- [ ] Database reset and seed script operates idempotently.
- [ ] Password entry is confirmed masked and excluded from graph state.
- [ ] Authorization boundaries between anonymous, client, and staff are verified.
- [ ] Transactional atomicity of quote creation is verified.
- [ ] Bounded diff is confirmed against the task-start baseline: only the example and this active SDD changed as part of this work; pre-existing user changes are preserved and reported separately.
- [ ] The local observability migration is additive and idempotent; business `demo.sqlite3` has not been reset or migrated.
- [ ] Redacted host error records and `--interaction` correlate incomplete runtime turns without rewriting runtime rows; successful interactions remain completed.
- [ ] Live quote persistence is approved only after exact customer/product/quantity/discount/total review; a provider failure leaves the business quote count unchanged and is inspectable by interaction ID.
- [ ] Mandatory Human Review Gate is satisfied by the user.

---

## Rollback Procedure

If any critical defect, architectural mismatch, or constraint violation occurs during implementation:

1. Stop the CLI and preserve the user's local business and observability databases.
2. Revert only the specific changes introduced by this hardening after comparing them with the task-start diff. Never delete the example directory, reset the worktree, or overwrite pre-existing user changes as a rollback shortcut.
3. Keep the active SDD and record the defect, affected files, and any safe recovery actions in this plan before reattempting.
