"""Privacy, secret filtering, and redaction test suite for Proteo telemetry database.

This module validates that sensitive canaries (passwords, tokens, API keys, raw prompts)
never leak into any column of any table in observability.sqlite3.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from database import init_database, seed_database  # noqa: E402
from graph import create_demo_graph  # noqa: E402
from models import AuthenticatedUser, DemoState  # noqa: E402
from observability import create_observability_config, get_observability_bus  # noqa: E402
from telemetry_db import init_telemetry_database  # noqa: E402

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind  # noqa: E402
from proteo_runtime.tools import ApprovalDecision, ApprovalHandler  # noqa: E402

DEMO_PASSWORD_CANARY = "DEMO_PASSWORD_CANARY_XYZ999"
DEMO_API_KEY_CANARY = "DEMO_API_KEY_CANARY_ABC123"
DEMO_SECRET_CANARY = "DEMO_SECRET_CANARY_SECRET456"
PROMPT_CANARY = "RAW_PROMPT_CANARY_DO_NOT_LEAK"
RESPONSE_CANARY = "RAW_RESPONSE_CANARY_DO_NOT_LEAK"


class AutoApprovalHandler(ApprovalHandler):
    """Test approval handler approving unconditionally."""

    async def request_approval(self, request: Any) -> ApprovalDecision:
        """Approve unconditionally.

        Args:
            request: Inbound approval request.

        Returns:
            Always ApprovalDecision.APPROVE.
        """
        return ApprovalDecision.APPROVE


def _search_all_tables_for_canaries(
    db_path: Path | str,
    canaries: list[str],
) -> dict[str, list[str]]:
    """Scan all columns across all 5 telemetry tables for occurrences of canary strings.

    Args:
        db_path: Target SQLite database.
        canaries: List of canary substrings to search for.

    Returns:
        Mapping of table_name -> list of found canary error messages.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    findings: dict[str, list[str]] = {}

    tables = [
        "runtime_events",
        "langsmith_runs",
        "otel_spans",
        "otel_span_events",
        "otel_metrics",
    ]

    try:
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            table_findings: list[str] = []
            for row in rows:
                for col_val in tuple(row):
                    val_str = str(col_val)
                    for canary in canaries:
                        if canary in val_str:
                            table_findings.append(f"Canary {canary!r} found in {table}: {val_str}")
            if table_findings:
                findings[table] = table_findings
        return findings
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_full_graph_interaction_zero_credential_leakage(tmp_path: Path) -> None:
    """Verify that interactive login and quote workflow leaks zero credentials to telemetry.

    Args:
        tmp_path: Temporary pytest directory.
    """
    demo_db = tmp_path / "demo.sqlite3"
    init_database(demo_db, reset=True)
    seed_database(demo_db)

    obs_db = tmp_path / "observability.sqlite3"
    init_telemetry_database(obs_db)

    conn = sqlite3.connect(str(demo_db))
    conn.row_factory = sqlite3.Row

    # Seed the staff user with our distinct password canary
    conn.execute(
        "UPDATE users SET password = ? WHERE username = 'staff'",
        (DEMO_PASSWORD_CANARY,),
    )
    conn.commit()

    obs_config = create_observability_config(mode="local", db_path=obs_db)
    bus = get_observability_bus(obs_config)

    from auth import authenticate_user_credentials

    # Custom login prompter supplying password canary to authenticate_user_credentials
    def fake_auth(c: sqlite3.Connection) -> AuthenticatedUser | None:
        return authenticate_user_credentials(c, "staff", DEMO_PASSWORD_CANARY)

    app_graph = create_demo_graph(
        conn,
        structured_model=None,
        context_agent=None,
        approval_handler=AutoApprovalHandler(),
        discount_prompter=lambda _subtotal: 10,
        auth_interactive=fake_auth,
        event_sink=bus.emit,
    )

    try:
        # 1. Turn 1: Login
        state1: DemoState = {
            "input": "login",
            "authenticated_user": None,
        }
        res1 = await app_graph.ainvoke(state1)
        user = res1.get("authenticated_user")
        assert user is not None

        # Verify password canary is NOT in DemoState
        assert DEMO_PASSWORD_CANARY not in str(res1)

        # 2. Turn 2: Quote creation
        state2: DemoState = {
            "input": "Create a quote for Globex for 2 Notebook Pro",
            "authenticated_user": user,
        }
        res2 = await app_graph.ainvoke(state2)
        assert res2.get("created_quote_id") is not None

        # Verify password canary is NOT in DemoState
        assert DEMO_PASSWORD_CANARY not in str(res2)
    finally:
        await bus.close()
        conn.close()

    # Search for canaries in all 5 telemetry tables
    canaries_to_check = [
        DEMO_PASSWORD_CANARY,
        DEMO_API_KEY_CANARY,
        DEMO_SECRET_CANARY,
    ]
    findings = _search_all_tables_for_canaries(obs_db, canaries_to_check)
    assert not findings, f"Sensitive canaries found in telemetry DB: {findings}"


@pytest.mark.asyncio
async def test_event_bus_metadata_only_redacts_sensitive_keys(tmp_path: Path) -> None:
    """Verify that event bus projects metadata only and strips sensitive keys and canaries.

    Args:
        tmp_path: Temporary pytest directory.
    """
    obs_db = tmp_path / "observability.sqlite3"
    init_telemetry_database(obs_db)

    obs_config = create_observability_config(mode="local", db_path=obs_db)
    bus = get_observability_bus(obs_config)

    now = datetime.now(UTC)

    # Layer 1 defense: Secret-shaped keys in metadata are rejected at construction
    with pytest.raises(ValueError, match="Secret-shaped metadata key is not permitted"):
        RuntimeEvent(
            kind=RuntimeEventKind.TOOL_REQUESTED,
            event_id="evt_reject_1",
            sequence=1,
            occurred_at=now,
            runtime="codex",
            metadata={"password": DEMO_PASSWORD_CANARY},
        )

    # Layer 2 defense: Sensitive metadata keys and embedded secrets are projected/redacted
    sensitive_event = RuntimeEvent(
        kind=RuntimeEventKind.TOOL_REQUESTED,
        event_id="evt_sensitive_1",
        sequence=1,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_canary_test",
        session_id="session_secret_test",
        metadata={
            "tool_name": "test_tool",
            "prompt": PROMPT_CANARY,
            "response": RESPONSE_CANARY,
            "auth_note": f"Bearer {DEMO_SECRET_CANARY}",
            "config_note": f"api_key={DEMO_API_KEY_CANARY}",
        },
    )

    try:
        await bus.emit(sensitive_event)
    finally:
        await bus.close()

    canaries_to_check = [
        DEMO_PASSWORD_CANARY,
        DEMO_API_KEY_CANARY,
        DEMO_SECRET_CANARY,
        PROMPT_CANARY,
        RESPONSE_CANARY,
    ]
    findings = _search_all_tables_for_canaries(obs_db, canaries_to_check)
    assert not findings, f"Canaries leaked into telemetry database: {findings}"


@pytest.mark.asyncio
async def test_concurrent_event_bus_emission(tmp_path: Path) -> None:
    """Verify concurrent event emission across 20 async tasks executes without database locking.

    Args:
        tmp_path: Temporary pytest directory.
    """
    obs_db = tmp_path / "obs_concurrent.sqlite3"
    init_telemetry_database(obs_db)

    obs_config = create_observability_config(mode="local", db_path=obs_db)
    bus = get_observability_bus(obs_config)

    async def worker(worker_id: int) -> None:
        for i in range(5):
            evt = RuntimeEvent(
                kind=RuntimeEventKind.TOOL_REQUESTED,
                event_id=f"evt_worker_{worker_id}_{i}",
                sequence=i + 1,
                occurred_at=datetime.now(UTC),
                runtime="codex",
                invocation_id=f"inv_worker_{worker_id}",
                metadata={
                    "tool_name": "list_products",
                    "worker_id": worker_id,
                    "iteration": i,
                },
            )
            await bus.emit(evt)

    try:
        tasks = [worker(w) for w in range(20)]
        await asyncio.gather(*tasks)
    finally:
        await bus.close()

    conn = sqlite3.connect(str(obs_db))
    try:
        count = conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
        assert count == 100
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_demo_password_1234_not_in_telemetry(tmp_path: Path) -> None:
    """Verify that default demo password '1234' is never written to telemetry metadata/attributes.

    Args:
        tmp_path: Temporary pytest directory.
    """
    demo_db = tmp_path / "demo_pwd.sqlite3"
    init_database(demo_db, reset=True)
    seed_database(demo_db)

    obs_db = tmp_path / "obs_pwd.sqlite3"
    init_telemetry_database(obs_db)

    conn = sqlite3.connect(str(demo_db))
    conn.row_factory = sqlite3.Row

    obs_config = create_observability_config(mode="local", db_path=obs_db)
    bus = get_observability_bus(obs_config)

    from auth import authenticate_user_credentials

    def fake_auth(c: sqlite3.Connection) -> AuthenticatedUser | None:
        return authenticate_user_credentials(c, "staff", "1234")

    app_graph = create_demo_graph(
        conn,
        structured_model=None,
        context_agent=None,
        approval_handler=AutoApprovalHandler(),
        discount_prompter=lambda _subtotal: 0,
        auth_interactive=fake_auth,
        event_sink=bus.emit,
    )

    try:
        state1: DemoState = {
            "input": "login",
            "authenticated_user": None,
        }
        res1 = await app_graph.ainvoke(state1)
        assert res1.get("authenticated_user") is not None
        assert "1234" not in str(res1)
    finally:
        await bus.close()
        conn.close()

    # Verify '1234' does not appear in metadata_json / attributes_json of telemetry tables
    conn_obs = sqlite3.connect(str(obs_db))
    conn_obs.row_factory = sqlite3.Row
    try:
        for table, col in [
            ("runtime_events", "metadata_json"),
            ("langsmith_runs", "metadata_json"),
            ("otel_spans", "attributes_json"),
            ("otel_span_events", "attributes_json"),
            ("otel_metrics", "attributes_json"),
        ]:
            rows = conn_obs.execute(f"SELECT {col} FROM {table}").fetchall()
            for row in rows:
                json_val = str(row[col] or "")
                assert "1234" not in json_val, f"Password '1234' found in {table}.{col}: {json_val}"
    finally:
        conn_obs.close()
