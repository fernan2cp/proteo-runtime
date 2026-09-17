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

from opentelemetry.sdk.metrics.export import MetricExportResult  # noqa: E402
from opentelemetry.sdk.trace.export import SpanExportResult  # noqa: E402
from otel_recording import (  # noqa: E402
    SQLiteMetricExporter,
    SQLiteSpanExporter,
    create_local_otel_bundle,
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


def test_sqlite_span_exporter_failure_handling(tmp_path: Path) -> None:
    """Verify SQLiteSpanExporter returns FAILURE, isolates exceptions, and records diagnostics."""
    from unittest.mock import MagicMock

    invalid_db = tmp_path / "non_existent_subdir" / "cannot_create" / "invalid.db"
    exporter = SQLiteSpanExporter(invalid_db)

    dummy_span = MagicMock()
    dummy_span.context.trace_id = 12345
    dummy_span.context.span_id = 67890
    dummy_span.parent = None
    dummy_span.name = "failing_span"
    dummy_span.start_time = 1000000000
    dummy_span.end_time = 2000000000
    dummy_span.kind.name = "INTERNAL"
    dummy_span.status.status_code.name = "OK"
    dummy_span.status.description = ""
    dummy_span.attributes = {}
    dummy_span.events = []

    res = exporter.export([dummy_span])
    assert res == SpanExportResult.FAILURE
    assert exporter.failure_count == 1
    assert exporter.last_error is not None


def test_sqlite_metric_exporter_failure_handling(tmp_path: Path) -> None:
    """Verify SQLiteMetricExporter returns FAILURE, isolates exceptions, and records diagnostics."""
    from unittest.mock import MagicMock

    invalid_db = tmp_path / "non_existent_subdir" / "cannot_create" / "invalid.db"
    exporter = SQLiteMetricExporter(invalid_db)

    dummy_dp = MagicMock()
    dummy_dp.value = 42.0
    dummy_dp.attributes = {}
    dummy_dp.time_unix_nano = 1000000000

    dummy_metric = MagicMock()
    dummy_metric.name = "failing_metric"
    dummy_metric.description = ""
    dummy_metric.unit = "1"
    dummy_metric.data.data_points = [dummy_dp]

    dummy_scope = MagicMock()
    dummy_scope.metrics = [dummy_metric]

    dummy_resource = MagicMock()
    dummy_resource.scope_metrics = [dummy_scope]

    metrics_data = MagicMock()
    metrics_data.resource_metrics = [dummy_resource]

    res = exporter.export(metrics_data)
    assert res == MetricExportResult.FAILURE
    assert exporter.failure_count == 1
    assert exporter.last_error is not None


def test_local_otel_bundle_lifecycle(temp_telemetry_db: Path) -> None:
    """Verify LocalOtelBundle force_flush and idempotent shutdown."""
    bundle = create_local_otel_bundle(temp_telemetry_db)
    tracer = bundle.tracer_provider.get_tracer("lifecycle-tracer")

    with tracer.start_as_current_span("lifecycle-span"):
        pass

    bundle.force_flush()
    spans = fetch_otel_spans(temp_telemetry_db)
    assert len(spans) == 1

    assert getattr(bundle, "is_shutdown") is False
    bundle.shutdown()
    assert getattr(bundle, "is_shutdown") is True
    # Idempotent call
    bundle.shutdown()
    assert getattr(bundle, "is_shutdown") is True


def test_delta_temporality_and_histogram_count(temp_telemetry_db: Path) -> None:
    """Verify DELTA temporality on exporter and count in histogram metrics."""
    import json

    bundle = create_local_otel_bundle(temp_telemetry_db)
    meter = bundle.meter_provider.get_meter("test-delta")

    hist = meter.create_histogram("test.latency", unit="ms")
    hist.record(100.0, attributes={"route": "pricing"})
    hist.record(200.0, attributes={"route": "pricing"})

    bundle.force_flush()

    metrics = fetch_recent_metrics(temp_telemetry_db)
    latency_metrics = [m for m in metrics if m["instrument_name"] == "test.latency"]
    assert len(latency_metrics) >= 1

    attrs = json.loads(latency_metrics[0]["attributes_json"])
    assert attrs.get("count") == 2
    assert latency_metrics[0]["value"] == 300.0

    bundle.shutdown()
