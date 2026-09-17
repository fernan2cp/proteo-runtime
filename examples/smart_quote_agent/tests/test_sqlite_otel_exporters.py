"""Unit tests for OpenTelemetry SQLite exporters and OpenTelemetryObserver integration."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Ensure examples/smart_quote_agent is on sys.path
_DEMO_DIR = Path(__file__).resolve().parent.parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from otel_recording import (  # noqa: E402
    create_local_otel_providers,
)
from telemetry_db import (  # noqa: E402
    fetch_otel_span_events,
    fetch_otel_spans,
    fetch_recent_metrics,
    init_telemetry_database,
)

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind  # noqa: E402
from proteo_runtime.observability.opentelemetry import OpenTelemetryObserver  # noqa: E402


@pytest.fixture
def temp_telemetry_db(tmp_path: Path) -> Path:
    """Provide an initialized clean telemetry database."""
    db_path = tmp_path / "otel_test.sqlite3"
    init_telemetry_database(db_path, reset=True)
    return db_path


def test_otel_providers_direct_export(temp_telemetry_db: Path) -> None:
    """Verify spans, span events, and metrics written directly via providers."""
    tracer_provider, meter_provider = create_local_otel_providers(temp_telemetry_db)

    tracer = tracer_provider.get_tracer("test-tracer")
    meter = meter_provider.get_meter("test-meter")

    # 1. Create a span with an event
    with tracer.start_as_current_span("test-span", attributes={"test.attr": "value"}) as span:
        span.add_event("approval_granted", attributes={"user": "alice"})

    # 2. Record counter
    counter = meter.create_counter("test.events", description="Test events counter")
    counter.add(5, attributes={"env": "test"})

    # Flush providers
    tracer_provider.force_flush()
    meter_provider.force_flush()

    # Verify spans
    spans = fetch_otel_spans(temp_telemetry_db)
    assert len(spans) == 1
    assert spans[0]["name"] == "test-span"
    assert "test.attr" in spans[0]["attributes_json"]

    # Verify span events
    span_id = spans[0]["span_id"]
    events = fetch_otel_span_events(temp_telemetry_db, span_id)
    assert len(events) == 1
    assert events[0]["name"] == "approval_granted"
    assert "alice" in events[0]["attributes_json"]

    # Verify metrics
    metrics = fetch_recent_metrics(temp_telemetry_db)
    assert len(metrics) >= 1
    metric_names = [m["instrument_name"] for m in metrics]
    assert "test.events" in metric_names


@pytest.mark.asyncio
async def test_opentelemetry_observer_integration(temp_telemetry_db: Path) -> None:
    """Verify real OpenTelemetryObserver records spans and metrics into SQLite tables."""
    tracer_provider, meter_provider = create_local_otel_providers(temp_telemetry_db)
    tracer = tracer_provider.get_tracer("proteo-runtime")
    meter = meter_provider.get_meter("proteo-runtime")

    observer = OpenTelemetryObserver(tracer=tracer, meter=meter)
    now = datetime.now(UTC)

    # 1. INVOCATION_STARTED
    evt1 = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="evt_start",
        sequence=1,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_otel_1",
        session_id="sess_1",
        metadata={"proteo.runtime": "codex", "proteo.model": "test-model"},
    )
    await observer.on_event(evt1)

    # 2. TOOL_COMPLETED
    evt2 = RuntimeEvent(
        kind=RuntimeEventKind.TOOL_COMPLETED,
        event_id="evt_tool",
        sequence=2,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_otel_1",
        session_id="sess_1",
        turn_id="turn_1",
        metadata={"tool_name": "list_products"},
    )
    await observer.on_event(evt2)

    # 3. INVOCATION_COMPLETED
    evt3 = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_COMPLETED,
        event_id="evt_comp",
        sequence=3,
        occurred_at=now,
        runtime="codex",
        invocation_id="inv_otel_1",
        session_id="sess_1",
        metadata={"status": "completed"},
    )
    await observer.on_event(evt3)

    tracer_provider.force_flush()
    meter_provider.force_flush()

    # Verify spans exist
    spans = fetch_otel_spans(temp_telemetry_db)
    assert len(spans) >= 1
    span_names = [s["name"] for s in spans]
    assert "proteo.invocation" in span_names

    # Verify metrics exist
    metrics = fetch_recent_metrics(temp_telemetry_db)
    assert len(metrics) >= 1
    metric_names = [m["instrument_name"] for m in metrics]
    assert "proteo.runtime.events" in metric_names
    assert "proteo.runtime.invocations" in metric_names
    assert "proteo.runtime.tool_calls" in metric_names
