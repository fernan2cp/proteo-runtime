"""Opt-in live integration smoke tests for Smart Quote Agent observability with real Codex.

These tests are intentionally skipped by default unless explicitly opted in via
PROTEO_CODEX_INTEGRATION=1 or RUN_CODEX_SMOKE=1.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from inspect_observability import inspect_telemetry  # noqa: E402
from observability import ObservabilityManager  # noqa: E402
from telemetry_db import (  # noqa: E402
    fetch_invocation_events,
    fetch_last_invocation_id,
    fetch_otel_spans,
    init_telemetry_database,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_INTEGRATION") != "1" and os.getenv("RUN_CODEX_SMOKE") != "1",
        reason="Real Codex smoke tests are opt-in (set PROTEO_CODEX_INTEGRATION=1 or RUN_CODEX_SMOKE=1)",
    ),
]


@pytest.fixture
def clean_smoke_obs_db(tmp_path: Path) -> Path:
    """Provide an initialized clean telemetry database for live smoke testing."""
    db_path = tmp_path / "smoke_observability.sqlite3"
    init_telemetry_database(db_path, reset=True)
    return db_path


@pytest.mark.asyncio
async def test_live_codex_observability_smoke(clean_smoke_obs_db: Path) -> None:
    """Execute one real Codex invocation and verify telemetry persistence and inspection."""
    from proteo_runtime.providers.codex import CodexRuntime

    obs_mgr = ObservabilityManager(mode="local", db_path=clean_smoke_obs_db)

    try:
        async with CodexRuntime(observability=obs_mgr.runtime_config) as runtime:
            model_target = await runtime.brain(level="low")
            result = await model_target.ainvoke("Reply with one word: 'OK'.")
            assert result.output
    finally:
        await obs_mgr.close()

    # 1. Verify telemetry database recorded the invocation
    last_inv_id = fetch_last_invocation_id(clean_smoke_obs_db)
    assert last_inv_id is not None

    events = fetch_invocation_events(clean_smoke_obs_db, last_inv_id)
    assert len(events) >= 2
    event_kinds = [e["event_kind"] for e in events]
    assert "invocation_started" in event_kinds
    assert "invocation_completed" in event_kinds

    # 2. Verify OpenTelemetry spans
    spans = fetch_otel_spans(clean_smoke_obs_db)
    assert len(spans) >= 1

    # 3. Verify inspector reports the invocation as completed
    inspection = inspect_telemetry(clean_smoke_obs_db, last=True)
    assert f"Invocation {last_inv_id}" in inspection
    assert "Status:     completed" in inspection
    assert "Runtime Events" in inspection
    assert "OpenTelemetry Spans" in inspection
