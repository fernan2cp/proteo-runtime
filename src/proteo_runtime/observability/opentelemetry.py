"""Optional OpenTelemetry observer over the neutral Proteo event contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind


class OpenTelemetryObserver:
    """Export spans and low-cardinality metrics without owning global providers."""

    def __init__(
        self, tracer: Any | None = None, meter: Any | None = None, *, name: str = "proteo-runtime"
    ) -> None:
        """Initialize with injected providers or the optional OpenTelemetry APIs."""

        if tracer is None or meter is None:
            try:
                from opentelemetry import metrics, trace
            except ImportError as exc:
                raise ImportError(
                    "OpenTelemetryObserver requires optional dependency; install proteo-runtime[otel]"
                ) from exc
            tracer = tracer or trace.get_tracer(name)
            meter = meter or metrics.get_meter(name)
        self.tracer = tracer
        self.meter = meter
        self._spans: dict[tuple[str, str], Any] = {}
        self._usage_seen: set[str] = set()
        self._closed = False
        self._event_counter = _instrument(
            meter, "create_counter", "proteo.runtime.events", "Runtime events"
        )
        self._invocation_counter = _instrument(
            meter, "create_counter", "proteo.runtime.invocations", "Invocations"
        )
        self._error_counter = _instrument(
            meter, "create_counter", "proteo.runtime.errors", "Runtime errors"
        )
        self._token_counter = _instrument(
            meter, "create_counter", "proteo.runtime.tokens", "Reported token usage"
        )
        self._retry_counter = _instrument(
            meter, "create_counter", "proteo.runtime.retries", "Retries"
        )
        self._tool_counter = _instrument(
            meter, "create_counter", "proteo.runtime.tool_calls", "Tool calls"
        )
        self._latency = _instrument(
            meter, "create_histogram", "proteo.runtime.duration", "Latency in milliseconds"
        )
        self._observability_failures = _instrument(
            meter,
            "create_counter",
            "proteo.observability.failures",
            "Observer failures",
        )

    async def on_event(self, event: RuntimeEvent) -> None:
        """Record one event as a span transition and metric point."""

        if self._closed:
            return
        invocation = event.invocation_id or event.event_id
        self._record_metric(self._event_counter, 1, {"event.kind": event.kind.value})
        if event.kind is RuntimeEventKind.INVOCATION_STARTED:
            self._record_metric(self._invocation_counter, 1, {"runtime": _runtime_name(event)})
        if event.kind is RuntimeEventKind.RETRY_SCHEDULED:
            self._record_metric(self._retry_counter, 1, {"runtime": _runtime_name(event)})
        if event.kind is RuntimeEventKind.TOOL_COMPLETED:
            self._record_metric(self._tool_counter, 1, {"runtime": _runtime_name(event)})
        if event.kind in {
            RuntimeEventKind.INVOCATION_FAILED,
            RuntimeEventKind.TURN_FAILED,
            RuntimeEventKind.TURN_INTERRUPTED,
        }:
            self._record_metric(self._error_counter, 1, {"event.kind": event.kind.value})
        if event.kind is RuntimeEventKind.TOKEN_USAGE_UPDATED:
            self._usage_seen.add(invocation)
            usage = event.metadata.get("usage")
            if isinstance(usage, Mapping):
                self._record_usage(usage, event)
        if event.kind is RuntimeEventKind.RUNTIME_STARTED:
            lifecycle_key = (f"lifecycle:{event.runtime}", "lifecycle")
            if lifecycle_key not in self._spans:
                span = self.tracer.start_span("proteo.runtime")
                _set_attributes(span, event)
                self._spans[lifecycle_key] = span
        elif event.kind is RuntimeEventKind.RUNTIME_STOPPED:
            self._end_span((f"lifecycle:{event.runtime}", "lifecycle"), event)
        if (
            event.kind
            in {
                RuntimeEventKind.SESSION_CREATED,
                RuntimeEventKind.SESSION_RESUMED,
            }
            and event.session_id
        ):
            session_key = (event.session_id, "session")
            if session_key not in self._spans:
                span = self.tracer.start_span("proteo.session")
                _set_attributes(span, event)
                self._spans[session_key] = span
        if (
            event.kind
            in {
                RuntimeEventKind.SESSION_CLOSED,
                RuntimeEventKind.SESSION_ARCHIVED,
                RuntimeEventKind.SESSION_DELETED,
            }
            and event.session_id
        ):
            self._end_span((event.session_id, "session"), event)
        key = (invocation, _span_kind(event.kind))
        if (
            event.kind
            in {
                RuntimeEventKind.INVOCATION_STARTED,
                RuntimeEventKind.TURN_STARTED,
                RuntimeEventKind.RETRY_SCHEDULED,
                RuntimeEventKind.VALIDATION_FAILED,
                RuntimeEventKind.TOOL_STARTED,
            }
            and key not in self._spans
        ):
            span = self.tracer.start_span(f"proteo.{key[1]}")
            _set_attributes(span, event)
            self._spans[key] = span
        if event.kind in {
            RuntimeEventKind.TURN_COMPLETED,
            RuntimeEventKind.TURN_FAILED,
            RuntimeEventKind.TURN_INTERRUPTED,
        }:
            self._end_span((invocation, "turn"), event)
        if event.kind in {RuntimeEventKind.RETRY_SCHEDULED, RuntimeEventKind.VALIDATION_FAILED}:
            parent = self._spans.get((invocation, "turn")) or self._spans.get(
                (invocation, "invocation")
            )
            if parent is not None and hasattr(parent, "add_event"):
                parent.add_event(
                    event.kind.value,
                    {
                        "attempt": str(event.metadata.get("attempt", "")),
                    },
                )
            self._end_span(key, event)
        if event.kind in {RuntimeEventKind.TOOL_COMPLETED}:
            self._end_span((invocation, "tool"), event)
        if event.kind in {
            RuntimeEventKind.INVOCATION_COMPLETED,
            RuntimeEventKind.INVOCATION_FAILED,
            RuntimeEventKind.CANCELLED,
            RuntimeEventKind.INTERRUPTED,
        }:
            self._end_span((invocation, "turn"), event)
            self._end_span((invocation, "invocation"), event)
            if event.result is not None and invocation not in self._usage_seen:
                self._record_usage(
                    {
                        token_type: getattr(event.result.usage, token_type)
                        for token_type in (
                            "input_tokens",
                            "cached_input_tokens",
                            "output_tokens",
                            "reasoning_tokens",
                            "total_tokens",
                        )
                    },
                    event,
                )
            if event.result is not None and event.result.usage.duration_ms is not None:
                self._record_metric(
                    self._latency, event.result.usage.duration_ms, {"runtime": _runtime_name(event)}
                )

    def _end_span(self, key: tuple[str, str], event: RuntimeEvent) -> None:
        """Set terminal status and end one tracked span."""

        span = self._spans.pop(key, None)
        if span is None:
            return
        failed = event.kind in {
            RuntimeEventKind.INVOCATION_FAILED,
            RuntimeEventKind.TURN_FAILED,
            RuntimeEventKind.TURN_INTERRUPTED,
            RuntimeEventKind.CANCELLED,
            RuntimeEventKind.INTERRUPTED,
        }
        if failed and hasattr(span, "set_status"):
            try:
                from opentelemetry.trace import Status, StatusCode

                span.set_status(
                    Status(StatusCode.ERROR, str(event.metadata.get("status", "failed")))
                )
            except ImportError:
                span.set_status("ERROR")
        exception_type = event.metadata.get("exception_type")
        if exception_type is not None and hasattr(span, "add_event"):
            span.add_event("exception", {"exception.type": str(exception_type)})
        if hasattr(span, "end"):
            span.end()

    def _record_metric(
        self, instrument: Any, value: int | float, attributes: Mapping[str, str]
    ) -> None:
        """Record metrics while keeping identifiers out of label cardinality."""

        if instrument is None:
            return
        add = getattr(instrument, "add", None)
        if add is not None:
            add(value, attributes=attributes)
        else:
            record = getattr(instrument, "record", None)
            if record is not None:
                record(value, attributes=attributes)

    def _record_usage(self, usage: Mapping[str, Any], event: RuntimeEvent) -> None:
        """Record known token counters with a bounded token-type label."""

        for token_type in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            value = usage.get(token_type)
            if isinstance(value, (int, float)):
                self._record_metric(
                    self._token_counter,
                    value,
                    {"runtime": _runtime_name(event), "token.type": token_type},
                )

    async def flush(self) -> None:
        """Leave provider lifecycle ownership with the host application."""

    async def close(self) -> None:
        """End observer-owned open spans without closing host providers."""

        if self._closed:
            return
        self._closed = True
        for span in tuple(self._spans.values()):
            if hasattr(span, "end"):
                span.end()
        self._spans.clear()

    def record_failure(self, observer_type: str) -> None:
        """Record an observer failure with a bounded observer-type label."""

        self._record_metric(
            self._observability_failures,
            1,
            {"observer.type": observer_type},
        )


def _instrument(meter: Any, method: str, name: str, description: str) -> Any:
    """Create one metric instrument when the injected meter supports it."""

    factory = getattr(meter, method, None)
    if factory is None:
        return None
    try:
        return factory(name, description=description)
    except TypeError:
        return factory(name)


def _span_kind(kind: RuntimeEventKind) -> str:
    """Map event kinds to bounded span names."""

    if kind is RuntimeEventKind.TURN_STARTED:
        return "turn"
    if kind is RuntimeEventKind.INVOCATION_STARTED:
        return "invocation"
    if kind in {RuntimeEventKind.RETRY_SCHEDULED, RuntimeEventKind.VALIDATION_FAILED}:
        return "retry" if kind is RuntimeEventKind.RETRY_SCHEDULED else "validation"
    if kind in {RuntimeEventKind.TOOL_STARTED, RuntimeEventKind.TOOL_COMPLETED}:
        return "tool"
    return "runtime"


def _set_attributes(span: Any, event: RuntimeEvent) -> None:
    """Attach safe correlation and runtime attributes to a span."""

    attrs = {
        "proteo.invocation_id": event.invocation_id,
        "proteo.session_id": event.session_id,
        "proteo.turn_id": event.turn_id,
        "proteo.runtime": _runtime_name(event),
    }
    for key in (
        "runtime.provider",
        "runtime.version",
        "profile",
        "security_policy",
        "context_policy",
        "model",
        "reasoning_effort",
        "ephemeral",
        "structured_output",
        "duration_ms",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "retry_count",
        "tool_call_count",
        "error.type",
        "error.code",
    ):
        if key in event.metadata:
            attrs[key] = event.metadata[key]
    if "exception_type" in event.metadata:
        attrs["error.type"] = event.metadata["exception_type"]
    for key, value in attrs.items():
        if (
            value is not None
            and isinstance(value, (str, int, float, bool))
            and hasattr(span, "set_attribute")
        ):
            span.set_attribute(key, value)


def _runtime_name(event: RuntimeEvent) -> str:
    """Return the provider name without serializing the identity object."""

    provider = getattr(event.runtime, "provider", None)
    return provider if isinstance(provider, str) else str(event.runtime)


__all__ = ["OpenTelemetryObserver"]
