"""OpenTelemetry SQLite exporters and provider configuration for Smart Quote Agent."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from opentelemetry.sdk.metrics import MeterProvider  # noqa: E402
from opentelemetry.sdk.metrics.export import (  # noqa: E402
    MetricExporter,
    MetricExportResult,
    MetricsData,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import (  # noqa: E402
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from telemetry_db import (  # noqa: E402
    get_telemetry_db_path,
    insert_otel_metric,
    insert_otel_span,
    insert_otel_span_event,
    utc_now_iso,
)


class SQLiteSpanExporter(SpanExporter):
    """OpenTelemetry SpanExporter persisting completed spans into otel_spans table."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize exporter with a target telemetry database path.

        Args:
            db_path: Target SQLite database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
        """
        self.db_path = get_telemetry_db_path(db_path)
        self._stopped = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a sequence of readable spans into the SQLite telemetry database.

        Args:
            spans: Sequence of finished ReadableSpan instances.

        Returns:
            SpanExportResult indicating SUCCESS or FAILURE.
        """
        if self._stopped:
            return SpanExportResult.FAILURE

        for span in spans:
            try:
                trace_id = format(span.context.trace_id, "032x")
                span_id = format(span.context.span_id, "016x")
                parent_span_id = (
                    format(span.parent.span_id, "016x")
                    if span.parent and span.parent.span_id
                    else None
                )
                name = span.name

                started_at = (
                    datetime.fromtimestamp(span.start_time / 1e9, tz=UTC).isoformat()
                    if span.start_time
                    else utc_now_iso()
                )
                ended_at = (
                    datetime.fromtimestamp(span.end_time / 1e9, tz=UTC).isoformat()
                    if span.end_time
                    else None
                )
                duration_ms = (
                    (span.end_time - span.start_time) / 1e6
                    if span.end_time and span.start_time
                    else None
                )

                status_code = (
                    span.status.status_code.name
                    if hasattr(span.status, "status_code")
                    else str(span.status)
                )
                status_message = (
                    span.status.description if hasattr(span.status, "description") else None
                )

                attributes = dict(span.attributes) if span.attributes else {}

                insert_otel_span(
                    self.db_path,
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    name=name,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_ms=duration_ms,
                    status_code=status_code,
                    status_message=status_message,
                    attributes=attributes,
                )

                # Persist any nested span events (e.g. approval, retry, validation)
                if span.events:
                    for event in span.events:
                        evt_ts = (
                            datetime.fromtimestamp(event.timestamp / 1e9, tz=UTC).isoformat()
                            if event.timestamp
                            else utc_now_iso()
                        )
                        evt_attrs = dict(event.attributes) if event.attributes else {}
                        insert_otel_span_event(
                            self.db_path,
                            span_id=span_id,
                            name=event.name,
                            occurred_at=evt_ts,
                            attributes=evt_attrs,
                        )
            except Exception:  # noqa: BLE001
                # Failures are isolated; do not crash the exporter loop
                continue

        return SpanExportResult.SUCCESS

    def shutdown(self, **kwargs: Any) -> None:
        """Shut down the exporter."""
        self._stopped = True

    def force_flush(self, timeout_millis: int = 30000, **kwargs: Any) -> bool:
        """Force flush pending spans."""
        return True


class SQLiteMetricExporter(MetricExporter):
    """OpenTelemetry MetricExporter persisting metric data points into otel_metrics table."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize metric exporter with target telemetry database path.

        Args:
            db_path: Target SQLite database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
        """
        super().__init__()
        self.db_path = get_telemetry_db_path(db_path)
        self._stopped = False

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        """Export MetricsData into otel_metrics in the SQLite database.

        Args:
            metrics_data: Aggregated OpenTelemetry MetricsData object.
            timeout_millis: Timeout limit in milliseconds.
            **kwargs: Extra unused keyword arguments.

        Returns:
            MetricExportResult indicating SUCCESS or FAILURE.
        """
        if self._stopped:
            return MetricExportResult.FAILURE

        for rm in metrics_data.resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    inst_name = metric.name
                    data_container = getattr(metric, "data", None)
                    if data_container is None:
                        continue

                    inst_type = type(data_container).__name__.lower()
                    data_points = getattr(data_container, "data_points", [])

                    for dp in data_points:
                        if hasattr(dp, "value"):
                            val = float(dp.value)
                        elif hasattr(dp, "sum"):
                            val = float(dp.sum)
                        elif hasattr(dp, "count"):
                            val = float(dp.count)
                        else:
                            val = 0.0

                        time_nano = getattr(dp, "time_unix_nano", None)
                        ts = (
                            datetime.fromtimestamp(time_nano / 1e9, tz=UTC).isoformat()
                            if time_nano
                            else utc_now_iso()
                        )
                        attrs = dict(dp.attributes) if getattr(dp, "attributes", None) else {}

                        insert_otel_metric(
                            self.db_path,
                            instrument_name=inst_name,
                            instrument_type=inst_type,
                            value=val,
                            recorded_at=ts,
                            attributes=attrs,
                        )

        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000, **kwargs: Any) -> bool:
        """Flush pending metrics."""
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        """Shut down the metric exporter."""
        self._stopped = True


def create_local_otel_providers(
    db_path: Path | str | None = None,
) -> tuple[TracerProvider, MeterProvider]:
    """Create and configure local OpenTelemetry TracerProvider and MeterProvider backed by SQLite.

    Args:
        db_path: Optional custom telemetry database path.

    Returns:
        Tuple of (TracerProvider, MeterProvider) configured with SQLite exporters.
    """
    tracer_provider = TracerProvider()
    span_exporter = SQLiteSpanExporter(db_path)
    span_processor = SimpleSpanProcessor(span_exporter)
    tracer_provider.add_span_processor(span_processor)

    metric_exporter = SQLiteMetricExporter(db_path)
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=50,  # fast periodic export for interactive responsiveness
    )
    meter_provider = MeterProvider(metric_readers=[metric_reader])

    return tracer_provider, meter_provider
