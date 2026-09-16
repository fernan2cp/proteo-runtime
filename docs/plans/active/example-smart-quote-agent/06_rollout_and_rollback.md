# Rollout and Rollback — Smart Quote Agent Example

## Rollout Strategy

The implementation of the Smart Quote Agent example progresses through five ordered delivery stages, ensuring that no unverified or non-conforming code enters the repository:

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

### Stage 5: Documentation & Mandatory Human Review Gate
- Complete `examples/smart_quote_agent/README.md`.
- Present the verified implementation to the repository owner.
- Upon explicit approval, move the SDD package from `docs/plans/active/example-smart-quote-agent/` to `docs/plans/complete/example-smart-quote-agent/`.

---

## Blast-Radius Analysis

| Scope Area | Impact Assessment | Mitigation & Guarantee |
|---|---|---|
| Core Runtime (`src/`) | **Zero Impact** | No core library files are modified or imported dynamically. |
| Existing Tests (`tests/`) | **Zero Impact** | Existing unit, integration, and quota-safety suites remain untouched. |
| Package Metadata (`pyproject.toml`, `uv.lock`) | **Zero Impact** | No new external dependencies are added; the example relies strictly on existing runtime dependencies (`langgraph`, `pydantic`, `sqlite3`). |
| Working Tree | **Strictly Bounded** | All created files are contained within `examples/smart_quote_agent/*`. |

---

## Verification Gates

Before presenting the work for final approval and moving the SDD to `complete`:

- [ ] Strict type checking passes (`uv run mypy examples/smart_quote_agent --strict`).
- [ ] Linting and formatting checks pass (`uv run ruff check`, `uv run ruff format --check`).
- [ ] Database reset and seed script operates idempotently.
- [ ] Password entry is confirmed masked and excluded from graph state.
- [ ] Authorization boundaries between anonymous, client, and staff are verified.
- [ ] Transactional atomicity of quote creation is verified.
- [ ] Working tree purity is confirmed (`git status --short` shows zero modifications outside `examples/smart_quote_agent/`).
- [ ] Mandatory Human Review Gate is satisfied by the user.

---

## Rollback Procedure

If any critical defect, architectural mismatch, or constraint violation occurs during implementation:

1. Delete the example directory:
   ```powershell
   Remove-Item -Recurse -Force examples/smart_quote_agent
   ```
2. Check git status to confirm a clean working tree:
   ```powershell
   git status --short
   ```
3. Record the reason for rollback in `ERRATA.md` or the active plan before reattempting.
