"""OpenTelemetry SQLite exporters and provider configuration for Smart Quote Agent."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider  # noqa: E402
from opentelemetry.sdk.metrics.export import (  # noqa: E402
    AggregationTemporality,
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

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        observer: Any | None = None,
    ) -> None:
        """Initialize exporter with a target telemetry database path.

        Args:
            db_path: Target SQLite database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
            observer: Optional parent observer instance for diagnostic failure reporting.
        """
        self.db_path = get_telemetry_db_path(db_path)
        self._observer = observer
        self._stopped = False
        self._last_error: Exception | None = None
        self._failure_count: int = 0

    @property
    def last_error(self) -> Exception | None:
        """Return the most recent exception encountered during export, if any.

        Returns:
            Exception instance or None.
        """
        return self._last_error

    @property
    def failure_count(self) -> int:
        """Return the number of export failures encountered.

        Returns:
            Total integer count of export failures.
        """
        return self._failure_count

    def set_observer(self, observer: Any) -> None:
        """Attach a parent observer for recording export failure metrics.

        Args:
            observer: Observer instance exposing record_failure.
        """
        self._observer = observer

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a sequence of readable spans into the SQLite telemetry database.

        Args:
            spans: Sequence of finished ReadableSpan instances.

        Returns:
            SpanExportResult indicating SUCCESS or FAILURE.
        """
        if self._stopped:
            return SpanExportResult.FAILURE

        success = True
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
            except Exception as exc:  # noqa: BLE001
                # Isolate persistence failures without crashing inference, but record diagnostic state
                self._last_error = exc
                self._failure_count += 1
                success = False
                if self._observer is not None and hasattr(self._observer, "record_failure"):
                    with contextlib.suppress(Exception):
                        self._observer.record_failure("SQLiteSpanExporter")
                continue

        return SpanExportResult.SUCCESS if success else SpanExportResult.FAILURE

    def shutdown(self, **kwargs: Any) -> None:
        """Shut down the exporter idempotently.

        Args:
            **kwargs: Extra unused keyword arguments.
        """
        self._stopped = True

    def force_flush(self, timeout_millis: int = 30000, **kwargs: Any) -> bool:
        """Force flush pending spans.

        Args:
            timeout_millis: Timeout limit in milliseconds.
            **kwargs: Extra unused keyword arguments.

        Returns:
            Always True for synchronous SQLite operations.
        """
        return True


class SQLiteMetricExporter(MetricExporter):
    """OpenTelemetry MetricExporter persisting metric data points into otel_metrics table."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        preferred_temporality: dict[type, AggregationTemporality] | None = None,
        observer: Any | None = None,
    ) -> None:
        """Initialize metric exporter with delta temporality to prevent double counting.

        Args:
            db_path: Target SQLite database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
            preferred_temporality: Optional temporality mapping. Defaults to DELTA for
                Counter and Histogram to avoid double counting across periodic exports.
            observer: Optional parent observer instance for diagnostic failure reporting.
        """
        if preferred_temporality is None:
            preferred_temporality = {
                Counter: AggregationTemporality.DELTA,
                Histogram: AggregationTemporality.DELTA,
            }
        super().__init__(preferred_temporality=preferred_temporality)
        self.db_path = get_telemetry_db_path(db_path)
        self._observer = observer
        self._stopped = False
        self._last_error: Exception | None = None
        self._failure_count: int = 0

    @property
    def last_error(self) -> Exception | None:
        """Return the most recent exception encountered during export, if any.

        Returns:
            Exception instance or None.
        """
        return self._last_error

    @property
    def failure_count(self) -> int:
        """Return the number of export failures encountered.

        Returns:
            Total integer count of export failures.
        """
        return self._failure_count

    def set_observer(self, observer: Any) -> None:
        """Attach a parent observer for recording export failure metrics.

        Args:
            observer: Observer instance exposing record_failure.
        """
        self._observer = observer

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

        success = True
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
                        try:
                            if hasattr(dp, "sum"):
                                val = float(dp.sum)
                            elif hasattr(dp, "value"):
                                val = float(dp.value)
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
                            # For histogram data points, preserve count in attributes for exact mean calculation
                            if hasattr(dp, "count") and "count" not in attrs:
                                attrs["count"] = int(dp.count)

                            insert_otel_metric(
                                self.db_path,
                                instrument_name=inst_name,
                                instrument_type=inst_type,
                                value=val,
                                recorded_at=ts,
                                attributes=attrs,
                            )
                        except Exception as exc:  # noqa: BLE001
                            self._last_error = exc
                            self._failure_count += 1
                            success = False
                            if self._observer is not None and hasattr(
                                self._observer, "record_failure"
                            ):
                                with contextlib.suppress(Exception):
                                    self._observer.record_failure("SQLiteMetricExporter")

        return MetricExportResult.SUCCESS if success else MetricExportResult.FAILURE

    def force_flush(self, timeout_millis: float = 10_000, **kwargs: Any) -> bool:
        """Flush pending metrics.

        Args:
            timeout_millis: Timeout limit in milliseconds.
            **kwargs: Extra unused keyword arguments.

        Returns:
            Always True for synchronous SQLite operations.
        """
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        """Shut down the metric exporter idempotently.

        Args:
            timeout_millis: Timeout limit in milliseconds.
            **kwargs: Extra unused keyword arguments.
        """
        self._stopped = True


class LocalOtelBundle:
    """Container for OpenTelemetry SDK providers and exporters with explicit lifecycle."""

    def __init__(
        self,
        tracer_provider: TracerProvider,
        meter_provider: MeterProvider,
        span_exporter: SQLiteSpanExporter,
        metric_exporter: SQLiteMetricExporter,
        metric_reader: PeriodicExportingMetricReader,
    ) -> None:
        """Initialize bundle with providers and exporters.

        Args:
            tracer_provider: SDK TracerProvider instance.
            meter_provider: SDK MeterProvider instance.
            span_exporter: SQLiteSpanExporter instance.
            metric_exporter: SQLiteMetricExporter instance.
            metric_reader: PeriodicExportingMetricReader instance.
        """
        self.tracer_provider = tracer_provider
        self.meter_provider = meter_provider
        self.span_exporter = span_exporter
        self.metric_exporter = metric_exporter
        self.metric_reader = metric_reader
        self._closed = False

    @property
    def is_shutdown(self) -> bool:
        """Return whether the OpenTelemetry bundle has been shut down.

        Returns:
            True if shut down, False otherwise.
        """
        return self._closed

    def force_flush(self, timeout_millis: int = 10000) -> bool:
        """Force flush providers and exporters idempotently.

        Args:
            timeout_millis: Timeout limit in milliseconds.

        Returns:
            True if all flushes succeeded, False otherwise.
        """
        if self._closed:
            return True
        tf_ok = True
        try:
            tf_ok = bool(self.tracer_provider.force_flush(timeout_millis=timeout_millis))
        except Exception:
            tf_ok = False
        mf_ok = True
        try:
            mf_ok = bool(self.meter_provider.force_flush(timeout_millis=timeout_millis))
        except Exception:
            mf_ok = False
        return tf_ok and mf_ok

    def shutdown(self) -> None:
        """Shut down providers and exporters idempotently."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            self.tracer_provider.shutdown()
        with contextlib.suppress(Exception):
            self.meter_provider.shutdown()


def create_local_otel_bundle(
    db_path: Path | str | None = None,
) -> LocalOtelBundle:
    """Create and configure local OpenTelemetry providers and exporters.

    Args:
        db_path: Optional custom telemetry database path.

    Returns:
        Configured LocalOtelBundle instance.
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

    return LocalOtelBundle(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        span_exporter=span_exporter,
        metric_exporter=metric_exporter,
        metric_reader=metric_reader,
    )


def create_local_otel_providers(
    db_path: Path | str | None = None,
) -> tuple[TracerProvider, MeterProvider]:
    """Create and configure local OpenTelemetry TracerProvider and MeterProvider backed by SQLite.

    Args:
        db_path: Optional custom telemetry database path.

    Returns:
        Tuple of (TracerProvider, MeterProvider) configured with SQLite exporters.
    """
    bundle = create_local_otel_bundle(db_path)
    return bundle.tracer_provider, bundle.meter_provider
