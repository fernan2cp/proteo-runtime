"""Unit coverage for neutral observability contracts and projections."""

from __future__ import annotations

import builtins
import sys
import types
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest

from proteo_runtime.core.diagnostics import RuntimeDiagnostic
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.model import RuntimeResult
from proteo_runtime.core.usage import RuntimeUsage
from proteo_runtime.observability import (
    ObservabilityConfig,
    ObserverBinding,
    PayloadMode,
    RuntimeEventBus,
)
from proteo_runtime.observability.bus import _project_value
from proteo_runtime.observability.langsmith import LangSmithObserver
from proteo_runtime.observability.opentelemetry import OpenTelemetryObserver
from proteo_runtime.providers.codex._runner import _item_text, _item_type
from proteo_runtime.providers.codex.native_otel import (
    CodexNativeOtelConfig,
    native_otel_capabilities,
)
from proteo_runtime.testing.fakes import FakeRuntime


class _Observer:
    """Collect events for bus assertions."""

    def __init__(self, fail: bool = False) -> None:
        """Initialize the collector."""

        self.events: list[RuntimeEvent] = []
        self.fail = fail
        self.closed = False

    async def on_event(self, event: RuntimeEvent) -> None:
        """Collect one projected event."""

        if self.fail:
            raise RuntimeError("secret=should-not-escape")
        self.events.append(event)

    async def flush(self) -> None:
        """Flush the in-memory collector."""

    async def close(self) -> None:
        """Mark the collector closed."""

        self.closed = True


class _FailLifecycle(_Observer):
    """Observer double that fails lifecycle operations."""

    async def flush(self) -> None:
        """Raise a safe flush failure."""

        raise RuntimeError("flush secret=hidden")

    async def close(self) -> None:
        """Raise a safe close failure."""

        raise RuntimeError("close secret=hidden")


class _TimeoutObserver(_Observer):
    """Observer double that never completes dispatch."""

    async def on_event(self, event: RuntimeEvent) -> None:
        """Block until cancelled."""

        del event
        import asyncio

        await asyncio.sleep(10)


class _LangClient:
    """Minimal synchronous LangSmith client double."""

    def __init__(self) -> None:
        """Initialize recorded calls."""

        self.created: list[dict[str, object]] = []
        self.updated: list[dict[str, object]] = []

    def create_run(self, **kwargs: object) -> dict[str, str]:
        """Record a run creation."""

        self.created.append(kwargs)
        return {"id": f"run-{len(self.created)}"}

    def update_run(self, **kwargs: object) -> None:
        """Record a run update."""

        self.updated.append(kwargs)


class _Span:
    """Small span double supporting status and attributes."""

    def __init__(self, name: str) -> None:
        """Initialize a named span."""

        self.name = name
        self.attributes: dict[str, object] = {}
        self.status: object | None = None
        self.events: list[tuple[str, Mapping[str, object]]] = []
        self.ended = False

    def set_attribute(self, key: str, value: object) -> None:
        """Record one attribute."""

        self.attributes[key] = value

    def set_status(self, value: object) -> None:
        """Record terminal status."""

        self.status = value

    def add_event(self, name: str, attributes: Mapping[str, object]) -> None:
        """Record one span event."""

        self.events.append((name, attributes))

    def end(self) -> None:
        """Mark the span ended."""

        self.ended = True


class _Tracer:
    """In-memory tracer double."""

    def __init__(self) -> None:
        """Initialize spans."""

        self.spans: list[_Span] = []

    def start_span(self, name: str) -> _Span:
        """Create and retain one span."""

        span = _Span(name)
        self.spans.append(span)
        return span


class _Metric:
    """Metric instrument double."""

    def __init__(self) -> None:
        """Initialize data points."""

        self.values: list[tuple[int | float, Mapping[str, str]]] = []

    def add(self, value: int | float, *, attributes: Mapping[str, str]) -> None:
        """Record a counter point."""

        self.values.append((value, attributes))

    def record(self, value: int | float, *, attributes: Mapping[str, str]) -> None:
        """Record a histogram point."""

        self.values.append((value, attributes))


class _Meter:
    """In-memory meter double."""

    def __init__(self) -> None:
        """Initialize instruments."""

        self.instruments: list[_Metric] = []

    def create_counter(self, name: str, **_: object) -> _Metric:
        """Create a counter."""

        del name
        metric = _Metric()
        self.instruments.append(metric)
        return metric

    def create_histogram(self, name: str, **_: object) -> _Metric:
        """Create a histogram."""

        del name
        metric = _Metric()
        self.instruments.append(metric)
        return metric


def _event(kind: RuntimeEventKind = RuntimeEventKind.INVOCATION_COMPLETED) -> RuntimeEvent:
    """Build a representative terminal event."""

    result = RuntimeResult(
        value="answer",
        usage=RuntimeUsage(total_tokens=3, duration_ms=1.0),
        runtime=RuntimeIdentity("fake", "identity"),
        model="fake-model",
        profile="brain",
        session_id="opaque-descriptor",
        diagnostics=(
            RuntimeDiagnostic(
                "test.diagnostic",
                "secret=should-not-escape",
                details={"nested": {"token": "secret"}},
            ),
        ),
    )
    return RuntimeEvent(
        kind,
        "invocation:1",
        0,
        datetime.now(UTC),
        RuntimeIdentity("fake", "identity"),
        "invocation",
        "opaque-descriptor",
        "turn",
        {"text": "prompt", "status": "completed"},
        result,
        {"text": "answer", "api_key": "secret"},
    )


@pytest.mark.asyncio
async def test_payload_modes_and_correlation_are_safe() -> None:
    """Project payloads according to all supported policies."""

    observers = {
        mode: _Observer()
        for mode in (PayloadMode.METADATA_ONLY, PayloadMode.REDACTED, PayloadMode.FULL)
    }
    bus = RuntimeEventBus(
        ObservabilityConfig(
            observers=tuple(ObserverBinding(observer, mode) for mode, observer in observers.items())
        )
    )
    await bus.emit(_event())
    assert observers[PayloadMode.METADATA_ONLY].events[0].result is None
    assert observers[PayloadMode.METADATA_ONLY].events[0].payload == {}
    redacted = observers[PayloadMode.REDACTED].events[0]
    assert redacted.metadata["text"] == "[REDACTED]"
    assert redacted.payload["text"] == "[REDACTED]"
    assert redacted.result is not None and redacted.result.value == "[REDACTED]"
    full = observers[PayloadMode.FULL].events[0]
    assert full.payload["text"] == "answer"
    assert full.payload["api_key"] == "[REDACTED]"
    assert full.session_id is not None and "opaque-descriptor" not in full.session_id
    assert full.result is not None and full.result.session_id == full.session_id
    assert full.result.diagnostics[0].message == "secret=[REDACTED]"
    assert full.result.diagnostics[0].details["nested"]["token"] == "[REDACTED]"
    assert "opaque-descriptor" not in str(full.metadata)
    assert str(full.metadata["proteo.session_id"]).startswith("proteo.session:")


@pytest.mark.asyncio
async def test_failures_degrade_and_strict_raises_after_fanout() -> None:
    """Isolated observer failures degrade by default and raise in strict mode."""

    good = _Observer()
    bad = _Observer(fail=True)
    bus = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(bad), ObserverBinding(good)), strict=False)
    )
    await bus.emit(_event())
    await bus.emit(
        RuntimeEvent(
            RuntimeEventKind.OUTPUT_TEXT_DELTA,
            "invocation:2",
            1,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            "invocation",
            payload={"text": "second"},
        )
    )
    assert bus.status.value == "degraded"
    assert len(bus.diagnostics) == 1
    assert len(good.events) == 2
    strict = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(bad), ObserverBinding(good)), strict=True)
    )
    with pytest.raises(Exception, match="Observability dispatch failed"):
        await strict.emit(_event())
    assert len(good.events) == 3


@pytest.mark.asyncio
async def test_bus_deduplicates_and_isolates_lifecycle_failures() -> None:
    """Exercise duplicate suppression, timeout diagnostics, and close idempotency."""

    good = _Observer()
    timeout = _TimeoutObserver()
    bus = RuntimeEventBus(
        ObservabilityConfig(
            observers=(ObserverBinding(timeout), ObserverBinding(good)),
            dispatch_timeout_seconds=0.001,
            shutdown_timeout_seconds=0.001,
        )
    )
    event = _event(RuntimeEventKind.INVOCATION_STARTED)
    await bus.emit(event)
    await bus.emit(event)
    assert len(good.events) == 1
    assert bus.diagnostics[0].details["exception_type"] == "TimeoutError"
    lifecycle = RuntimeEventBus(ObservabilityConfig(observers=(ObserverBinding(_FailLifecycle()),)))
    await lifecycle.flush()
    await lifecycle.close()
    await lifecycle.close()
    assert lifecycle.status.value == "degraded"
    strict_lifecycle = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(_FailLifecycle()),), strict=True)
    )
    with pytest.raises(Exception, match="Observability (flush|close) failed"):
        await strict_lifecycle.close()
    diagnostics = strict_lifecycle.diagnostics
    await strict_lifecycle.close()
    assert strict_lifecycle.diagnostics == diagnostics


@pytest.mark.asyncio
async def test_terminal_dispatch_cleanup_survives_active_cancellation() -> None:
    """Release terminal invocation state when an observer inherits cancellation."""

    observer = _TimeoutObserver()
    bus = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(observer),), dispatch_timeout_seconds=10.0)
    )
    task = __import__("asyncio").create_task(bus.emit(_event()))
    await __import__("asyncio").sleep(0)
    task.cancel()
    with pytest.raises(__import__("asyncio").CancelledError):
        await task
    assert not bus._locks


def test_projection_handles_nested_values_and_secret_canaries() -> None:
    """Cover recursive mappings, sequences, objects, and secret-shaped strings."""

    value = {
        "nested": {"token": "abc", "value": 4},
        "items": ["secret=x", 2],
        "set": {"x", "y"},
        "object": object(),
    }
    projected = _project_value(value, PayloadMode.FULL, None)
    assert projected["nested"]["token"] == "[REDACTED]"
    assert "[REDACTED]" in projected["items"][0]
    assert len(projected["set"]) == 2
    assert projected["object"] == "<object>"
    assert _project_value(2, PayloadMode.REDACTED, None) == "<int>"
    assert "provider_payload" not in _project_value(
        {"provider_payload": {"secret": "x"}, "text": "ok"}, PayloadMode.FULL, None
    )


def test_runtime_event_payload_requires_a_mapping() -> None:
    """Reject non-mapping payloads at the immutable event boundary."""

    with pytest.raises(TypeError, match="payload"):
        RuntimeEvent(
            RuntimeEventKind.OUTPUT_TEXT_DELTA,
            "invalid-payload",
            0,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            payload=["not", "a", "mapping"],  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_redacted_metadata_preserves_operational_shape_and_hashes_session_keys() -> None:
    """Keep safe metadata useful while redacting content and descriptor aliases."""

    observer = _Observer()
    bus = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(observer, PayloadMode.REDACTED),))
    )
    event = RuntimeEvent(
        RuntimeEventKind.INVOCATION_STARTED,
        "metadata",
        0,
        datetime.now(UTC),
        RuntimeIdentity("fake", "identity"),
        "invocation",
        metadata={
            "model": "fake-model",
            "prompt": "do not retain",
            "session_id": "opaque-descriptor",
            "nested": {"authorization": "secret"},
        },
    )
    await bus.emit(event)
    projected = observer.events[0]
    assert projected.metadata["model"] == "fake-model"
    assert projected.metadata["prompt"] == "[REDACTED]"
    assert str(projected.metadata["session_id"]).startswith("proteo.session:")
    assert projected.metadata["nested"]["authorization"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_metadata_only_hashes_descriptor_aliases_and_bounds_runtime_name() -> None:
    """Keep migration descriptors and unsafe runtime labels out of metadata exports."""

    observer = _Observer()
    bus = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(observer, PayloadMode.METADATA_ONLY),))
    )
    event = RuntimeEvent(
        RuntimeEventKind.SESSION_MIGRATED,
        "migration",
        0,
        datetime.now(UTC),
        "runtime secret",
        metadata={
            "old_session_id": "opaque-old",
            "new_session_id": "opaque-new",
            "descriptor": "must-not-escape",
            "headers": {"authorization": "Bearer secret"},
        },
    )
    await bus.emit(event)
    projected = observer.events[0]
    assert str(projected.metadata["old_session_id"]).startswith("proteo.session:")
    assert str(projected.metadata["new_session_id"]).startswith("proteo.session:")
    assert projected.metadata["proteo.runtime"] == "unknown"
    assert "descriptor" not in projected.metadata
    assert "headers" not in projected.metadata


@pytest.mark.asyncio
async def test_otel_failure_accounting_isolated_by_bus() -> None:
    """Record observer failure metrics without allowing accounting to raise."""

    class FailingTracer:
        """Tracer double that fails while creating a span."""

        def start_span(self, name: str) -> _Span:
            """Raise a provider-neutral failure."""

            del name
            raise RuntimeError("span provider unavailable")

    meter = _Meter()
    observer = OpenTelemetryObserver(FailingTracer(), meter)
    bus = RuntimeEventBus(ObservabilityConfig(observers=(ObserverBinding(observer),)))
    await bus.emit(_event(RuntimeEventKind.RUNTIME_STARTED))
    assert bus.status is not None
    assert any(metric.values for metric in meter.instruments)


def test_runner_item_helpers_support_nested_provider_shapes() -> None:
    """Normalize root-wrapped and content-wrapped message items safely."""

    class Content:
        """Nested content double."""

        text = "nested"

    class Item:
        """Root item double."""

        type = "agentMessage"
        content = (Content(),)

    assert _item_text(Item()) == "nested"
    assert _item_type(Item()) == "agentMessage"


@pytest.mark.asyncio
async def test_disabled_binding_does_not_change_health() -> None:
    """Disabled bindings do not dispatch or activate the bus."""

    observer = _Observer()
    bus = RuntimeEventBus(
        ObservabilityConfig(observers=(ObserverBinding(observer, PayloadMode.DISABLED),))
    )
    await bus.emit(_event(RuntimeEventKind.RUNTIME_STARTED))
    assert bus.status.value == "disabled"


def test_invalid_observability_configuration_fails_early() -> None:
    """Reject duplicate observers and invalid timeout values before use."""

    observer = _Observer()
    assert ObserverBinding(observer, "full").payload_mode is PayloadMode.FULL
    with pytest.raises(TypeError):
        ObserverBinding(cast(Any, object()))
    with pytest.raises(TypeError):
        ObservabilityConfig(observers=cast(Any, (object(),)))
    with pytest.raises(ValueError):
        ObservabilityConfig(observers=(ObserverBinding(observer), ObserverBinding(observer)))
    with pytest.raises(ValueError):
        ObservabilityConfig(dispatch_timeout_seconds=0)
    with pytest.raises(ValueError):
        ObservabilityConfig(dispatch_timeout_seconds=float("nan"))


@pytest.mark.asyncio
async def test_langsmith_hierarchy_and_lifecycle_use_injected_client() -> None:
    """Map runtime, turn, retry, validation, and terminal events to runs."""

    client = _LangClient()
    observer = LangSmithObserver(client, project_name="tests", tags=("unit",))
    for kind in (
        RuntimeEventKind.INVOCATION_STARTED,
        RuntimeEventKind.TURN_STARTED,
        RuntimeEventKind.RETRY_SCHEDULED,
        RuntimeEventKind.VALIDATION_FAILED,
        RuntimeEventKind.INVOCATION_COMPLETED,
    ):
        await observer.on_event(_event(kind))
    await observer.flush()
    await observer.close()
    assert len(client.created) == 4
    assert len(client.updated) == 4


@pytest.mark.asyncio
async def test_langsmith_tolerates_legacy_clients_and_missing_methods() -> None:
    """Exercise compatibility fallbacks and safe parent metadata handling."""

    class LegacyClient:
        """Client with a reduced keyword surface."""

        def create_run(
            self,
            *,
            name: str,
            run_type: str,
            inputs: object,
            extra: object,
            tags: object,
            **_: object,
        ) -> str:
            """Return a scalar run ID."""

            del name, run_type, inputs, extra, tags
            return "legacy-run"

        def update_run(self, *, run_id: str, outputs: object, **_: object) -> None:
            """Accept reduced update calls."""

            del run_id, outputs

    observer = LangSmithObserver(LegacyClient())
    event = _event(RuntimeEventKind.INVOCATION_STARTED)
    event = RuntimeEvent(
        event.kind,
        event.event_id,
        event.sequence,
        event.occurred_at,
        event.runtime,
        event.invocation_id,
        event.session_id,
        event.turn_id,
        {"langgraph_run_id": "graph-parent"},
        event.result,
        event.payload,
    )
    await observer.on_event(event)
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_FAILED))
    await LangSmithObserver(object()).on_event(_event(RuntimeEventKind.RUNTIME_STARTED))


@pytest.mark.asyncio
async def test_langsmith_client_ownership_is_explicit() -> None:
    """Close only a client whose lifecycle was assigned to the observer."""

    class Closable:
        """Client double exposing close."""

        def __init__(self) -> None:
            """Initialize close state."""

            self.closed = False

        def close(self) -> None:
            """Mark the client closed."""

            self.closed = True

    borrowed = Closable()
    await LangSmithObserver(borrowed).close()
    assert not borrowed.closed
    owned = Closable()
    await LangSmithObserver(owned, owns_client=True).close()
    assert owned.closed


@pytest.mark.asyncio
async def test_langsmith_tool_runs_and_terminal_outputs_are_serializable() -> None:
    """Keep one tool run per call and close runtime only at invocation terminal."""

    client = _LangClient()
    observer = LangSmithObserver(client)
    runtime = RuntimeIdentity("fake", "identity")
    result = RuntimeResult(
        value={"answer": ["ok", 1]},
        usage=RuntimeUsage(total_tokens=2),
        runtime=runtime,
        model="fake-model",
        profile="brain",
    )

    def event(kind: RuntimeEventKind, sequence: int, **kwargs: Any) -> RuntimeEvent:
        """Build one event for the hierarchy fixture."""

        return RuntimeEvent(
            kind,
            f"hierarchy:{sequence}",
            sequence,
            datetime.now(UTC),
            runtime,
            "hierarchy",
            None,
            "turn",
            kwargs.get("metadata", {}),
            kwargs.get("result"),
            kwargs.get("payload", {}),
        )

    parent = str(uuid4())
    await observer.on_event(
        event(RuntimeEventKind.INVOCATION_STARTED, 0, metadata={"langgraph_run_id": parent})
    )
    await observer.on_event(event(RuntimeEventKind.TURN_STARTED, 1))
    await observer.on_event(
        event(
            RuntimeEventKind.TOOL_REQUESTED,
            2,
            metadata={"tool_name": "search"},
            payload={"args": [{"query": "safe"}]},
        )
    )
    await observer.on_event(
        event(RuntimeEventKind.TOOL_STARTED, 3, metadata={"tool_name": "search"})
    )
    await observer.on_event(
        event(
            RuntimeEventKind.TOOL_COMPLETED,
            4,
            metadata={"tool_name": "search"},
            payload={"result": {"ok": True}},
        )
    )
    await observer.on_event(
        event(RuntimeEventKind.TURN_COMPLETED, 5, metadata={"status": "completed"})
    )
    await observer.on_event(
        event(
            RuntimeEventKind.INVOCATION_COMPLETED,
            6,
            metadata={"status": "completed"},
            result=result,
        )
    )
    assert [entry["name"] for entry in client.created] == [
        "proteo.runtime",
        "proteo.turn",
        "proteo.tool",
    ]
    assert len(client.updated) == 3
    assert client.created[0]["parent_run_id"] == parent
    outputs = cast(dict[str, Any], client.updated[-1]["outputs"])
    assert outputs["value"] == {"answer": ["ok", 1]}


def test_langsmith_import_guard_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report the optional extra when LangSmith cannot be imported."""

    original: Any = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        """Block only the optional LangSmith import."""

        if name == "langsmith":
            raise ImportError("missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(ImportError, match="langsmith"):
        LangSmithObserver()


@pytest.mark.asyncio
async def test_otel_injected_providers_record_spans_and_metrics() -> None:
    """Record safe IDs, status, and metrics without global provider ownership."""

    tracer, meter = _Tracer(), _Meter()
    observer = OpenTelemetryObserver(tracer, meter)
    await observer.on_event(_event(RuntimeEventKind.RUNTIME_STARTED))
    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.SESSION_CREATED,
            "session-created",
            0,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            session_id="opaque-descriptor",
        )
    )
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_STARTED))
    await observer.on_event(_event(RuntimeEventKind.TURN_STARTED))
    await observer.on_event(_event(RuntimeEventKind.RETRY_SCHEDULED))
    await observer.on_event(_event(RuntimeEventKind.VALIDATION_FAILED))
    await observer.on_event(_event(RuntimeEventKind.TOOL_STARTED))
    await observer.on_event(_event(RuntimeEventKind.TOOL_COMPLETED))
    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.TOKEN_USAGE_UPDATED,
            "usage",
            1,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            "invocation",
            metadata={"usage": {"total_tokens": 3}},
        )
    )
    await observer.on_event(_event(RuntimeEventKind.TURN_COMPLETED))
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_COMPLETED))
    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.SESSION_CLOSED,
            "session-closed",
            1,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            session_id="opaque-descriptor",
        )
    )
    await observer.on_event(_event(RuntimeEventKind.RUNTIME_STOPPED))
    await observer.flush()
    await observer.close()
    assert tracer.spans and all(span.ended for span in tracer.spans)
    assert meter.instruments and any(metric.values for metric in meter.instruments)
    assert all(
        "invocation" not in attrs for metric in meter.instruments for _, attrs in metric.values
    )


@pytest.mark.asyncio
async def test_otel_failed_terminal_sets_error_and_supports_record_only_metrics() -> None:
    """Exercise error status, histogram recording, and missing optional instruments."""

    class RecordOnly:
        """Histogram-like instrument with record only."""

        def __init__(self) -> None:
            """Initialize records."""

            self.values: list[float] = []

        def record(self, value: float, *, attributes: Mapping[str, str]) -> None:
            """Record a value."""

            del attributes
            self.values.append(value)

    class Meter:
        """Meter exposing only a record-only histogram."""

        def create_histogram(self, name: str) -> RecordOnly:
            """Create a histogram."""

            del name
            return RecordOnly()

    tracer = _Tracer()
    observer = OpenTelemetryObserver(tracer, Meter())
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_STARTED))
    failed = RuntimeEvent(
        RuntimeEventKind.INVOCATION_FAILED,
        "failed",
        1,
        datetime.now(UTC),
        RuntimeIdentity("fake", "identity"),
        "invocation",
        metadata={"status": "failed", "exception_type": "ValueError"},
    )
    await observer.on_event(failed)
    assert tracer.spans[0].ended
    assert tracer.spans[0].events == [("exception", {"exception.type": "ValueError"})]


@pytest.mark.asyncio
async def test_otel_handles_provider_without_metric_factories() -> None:
    """Treat missing metric factories as a valid host-owned provider choice."""

    observer = OpenTelemetryObserver(_Tracer(), object())
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_STARTED))
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_COMPLETED))


@pytest.mark.asyncio
async def test_otel_close_ends_open_spans_without_owning_provider() -> None:
    """Close an incomplete observer span while leaving injected providers untouched."""

    tracer = _Tracer()
    observer = OpenTelemetryObserver(tracer, object())
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_STARTED))
    await observer.close()
    await observer.close()
    assert tracer.spans[0].ended


@pytest.mark.asyncio
async def test_otel_sdk_in_memory_export_is_supported_when_dev_extra_is_installed() -> None:
    """Exercise the official SDK providers without network or global provider mutation."""

    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    export_sdk = pytest.importorskip("opentelemetry.sdk.trace.export")
    metrics_sdk = pytest.importorskip("opentelemetry.sdk.metrics")
    metrics_export_sdk = pytest.importorskip("opentelemetry.sdk.metrics.export")
    in_memory_module = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    span_exporter = in_memory_module.InMemorySpanExporter()
    tracer_provider = trace_sdk.TracerProvider()
    tracer_provider.add_span_processor(export_sdk.SimpleSpanProcessor(span_exporter))
    metric_reader = metrics_export_sdk.InMemoryMetricReader()
    meter_provider = metrics_sdk.MeterProvider(metric_readers=[metric_reader])
    observer = OpenTelemetryObserver(
        tracer_provider.get_tracer("tests"), meter_provider.get_meter("tests")
    )
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_STARTED))
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_COMPLETED))
    await observer.close()
    assert span_exporter.get_finished_spans()
    assert metric_reader.get_metrics_data() is not None


@pytest.mark.asyncio
async def test_otel_lazy_api_import_uses_host_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise optional API loading without replacing process globals."""

    tracer = _Tracer()
    meter = _Meter()
    trace_module = types.ModuleType("opentelemetry.trace")
    trace_module.get_tracer = lambda name: tracer  # type: ignore[attr-defined]
    trace_module.Status = lambda *args: args  # type: ignore[attr-defined]
    trace_module.StatusCode = types.SimpleNamespace(ERROR="ERROR")  # type: ignore[attr-defined]
    metrics_module = types.ModuleType("opentelemetry.metrics")
    metrics_module.get_meter = lambda name: meter  # type: ignore[attr-defined]
    otel_module = types.ModuleType("opentelemetry")
    otel_module.trace = trace_module  # type: ignore[attr-defined]
    otel_module.metrics = metrics_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", otel_module)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_module)
    monkeypatch.setitem(sys.modules, "opentelemetry.metrics", metrics_module)
    observer = OpenTelemetryObserver(name="test")
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_STARTED))
    await observer.on_event(_event(RuntimeEventKind.INVOCATION_FAILED))
    assert tracer.spans[0].ended


@pytest.mark.asyncio
async def test_fake_runtime_uses_one_bus_for_invoke_stream_and_sessions() -> None:
    """Verify result status and exact-once dispatch across fake runtime paths."""

    observer = _Observer()
    runtime = FakeRuntime(observability=ObservabilityConfig(observers=(ObserverBinding(observer),)))
    await runtime.start()
    result = await runtime.model(profile="brain").ainvoke("hello")
    assert result.observability_status.value == "healthy"
    session = await runtime.session()
    await session.ainvoke("hello")
    await session.close()
    await runtime.close()
    assert len(observer.events) == len({event.event_id for event in observer.events})


def test_native_otel_configuration_is_private_and_capability_gated() -> None:
    """Build safe Codex overrides and report unsupported propagation honestly."""

    config = CodexNativeOtelConfig(
        enabled=True,
        endpoint="https://collector.example/v1/traces",
        resource_attributes={"deployment.environment": "test"},
        log_user_prompt=True,
    )
    overrides = config.overrides()
    assert "otel.log_user_prompt=false" in overrides
    assert not any("header" in value.casefold() for value in overrides)
    capabilities = native_otel_capabilities(config)
    assert capabilities.configured and not capabilities.correlation_propagation
    assert native_otel_capabilities(None).reason == "disabled"
    with pytest.raises(ValueError):
        CodexNativeOtelConfig(enabled=True, endpoint="https://user:pass@collector.invalid")
    with pytest.raises(ValueError):
        CodexNativeOtelConfig(exporter="unsupported")
    with pytest.raises(ValueError):
        CodexNativeOtelConfig(protocol="unsupported")
    with pytest.raises(ValueError):
        CodexNativeOtelConfig(enabled=True, endpoint="https://collector.invalid?token=secret")
    with pytest.raises(ValueError):
        CodexNativeOtelConfig(resource_attributes={"api_key": "secret"})


@pytest.mark.asyncio
async def test_otel_records_task_spans_and_attributes() -> None:
    """Validate OpenTelemetryObserver records task spans and proteo.task_id attribute."""
    tracer, meter = _Tracer(), _Meter()
    observer = OpenTelemetryObserver(tracer, meter)

    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.TASK_STARTED,
            "task-start-1",
            0,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            task_id="task_12345",
            metadata={"profile": "controlled_agent", "model": "test-model"},
        )
    )
    assert len(tracer.spans) == 1
    task_span = tracer.spans[0]
    assert task_span.name == "proteo.task"
    assert task_span.attributes.get("proteo.task_id") == "task_12345"
    assert not task_span.ended

    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.INVOCATION_STARTED,
            "inv-start-1",
            1,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            invocation_id="inv-1",
            task_id="task_12345",
        )
    )
    inv_span = tracer.spans[-1]
    assert inv_span.name == "proteo.invocation"
    assert inv_span.attributes.get("proteo.task_id") == "task_12345"

    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.TASK_CLOSED,
            "task-close-1",
            2,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            task_id="task_12345",
        )
    )
    assert task_span.ended


@pytest.mark.asyncio
async def test_langsmith_observer_projects_proteo_task_id() -> None:
    """Validate LangSmithObserver projects metadata['proteo_task_id']."""
    client = _LangClient()
    observer = LangSmithObserver(client=client)

    await observer.on_event(
        RuntimeEvent(
            RuntimeEventKind.INVOCATION_STARTED,
            "inv-1",
            0,
            datetime.now(UTC),
            RuntimeIdentity("fake", "identity"),
            invocation_id="inv-1",
            task_id="task_abc",
        )
    )
    assert len(client.created) == 1
    run = client.created[0]
    extra = cast(dict[str, Any], run.get("extra", {}))
    metadata = cast(dict[str, Any], extra.get("metadata", {}))
    assert metadata.get("proteo_task_id") == "task_abc"
