"""Unit tests ensuring raw Codex thread IDs never leak into public contracts or telemetry.

Adheres strictly to AC-CAL-021: raw Codex thread IDs are absent from all
public telemetry and events.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.model import RuntimeResult, RuntimeUsage
from proteo_runtime.integrations.langgraph import RuntimeNode
from proteo_runtime.observability import (
    ObservabilityConfig,
    ObserverBinding,
    PayloadMode,
    RuntimeEventBus,
    RuntimeObserver,
)
from proteo_runtime.observability.langsmith import LangSmithObserver
from proteo_runtime.observability.opentelemetry import OpenTelemetryObserver
from proteo_runtime.providers.codex.experimental import CodexToolBridge, CodexToolMux
from proteo_runtime.providers.codex.runtime import CodexRuntime
from proteo_runtime.tools import (
    ToolExecutor,
    ToolPermissionPolicy,
    ToolRegistry,
    runtime_tool,
)

# Ensure tests/unit is available on path
_unit_dir = str(Path(__file__).resolve().parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import (  # noqa: E402
    FakeSDK,
    FakeThread,
    install_sdk,
)

CANARY_THREAD_ID = "thread-SECRET-INTERNAL-123"


def assert_no_canary_leak(
    target: object,
    canary: str = CANARY_THREAD_ID,
    path: str = "root",
) -> None:
    """Recursively verify that a secret canary string does not leak into an object.

    Args:
        target: Any object, dataclass, mapping, sequence, or primitive to inspect.
        canary: Canary string that must never appear.
        path: Path descriptor for diagnostic error messages.

    Raises:
        AssertionError: If the canary is found in any field, key, value, or representation.
    """
    if target is None or isinstance(target, int | float | bool):
        return

    if isinstance(target, str):
        assert canary not in target, f"Canary leaked into string at {path}: {target!r}"
        return

    if isinstance(target, bytes | bytearray):
        assert canary.encode("utf-8") not in target, f"Canary leaked into bytes at {path}"
        return

    if isinstance(target, Mapping):
        for key, value in target.items():
            key_str = str(key)
            assert canary not in key_str, f"Canary leaked into mapping key at {path}.{key_str}"
            assert_no_canary_leak(value, canary, f"{path}.{key_str}")
        return

    if isinstance(target, Sequence | set | frozenset):
        for index, item in enumerate(target):
            assert_no_canary_leak(item, canary, f"{path}[{index}]")
        return

    if is_dataclass(target) and not isinstance(target, type):
        for dc_field in fields(target):
            assert_no_canary_leak(getattr(target, dc_field.name), canary, f"{path}.{dc_field.name}")
        return

    if hasattr(target, "__dict__"):
        for attr, val in target.__dict__.items():
            if not attr.startswith("_"):
                assert_no_canary_leak(val, canary, f"{path}.{attr}")


class CanarySDK(FakeSDK):
    """FakeSDK subclass whose threads always use CANARY_THREAD_ID."""

    async def thread_start(self, **kwargs: Any) -> FakeThread:
        """Create a fake thread tagged with the canary thread ID.

        Args:
            **kwargs: Thread creation parameters.

        Returns:
            FakeThread instance with CANARY_THREAD_ID.
        """
        self.start_calls.append(kwargs)
        return FakeThread(self, CANARY_THREAD_ID)

    async def thread_resume(self, thread_id: str, **kwargs: Any) -> FakeThread:
        """Resume a fake thread tagged with the canary thread ID.

        Args:
            thread_id: Requested thread ID.
            **kwargs: Additional parameters.

        Returns:
            FakeThread instance with CANARY_THREAD_ID.
        """
        self.resume_calls.append((thread_id, kwargs))
        return FakeThread(self, CANARY_THREAD_ID)


class RecordingObserver:
    """Observer double that collects all projected events."""

    def __init__(self) -> None:
        """Initialize empty event log."""
        self.events: list[RuntimeEvent] = []

    async def on_event(self, event: RuntimeEvent) -> None:
        """Record one projected event.

        Args:
            event: The projected runtime event.
        """
        self.events.append(event)

    async def flush(self) -> None:
        """Flush observer buffer."""

    async def close(self) -> None:
        """Release observer resources."""


class RecordingLangSmithClient:
    """Mock LangSmith client capturing create_run and update_run calls."""

    def __init__(self) -> None:
        """Initialize call logs."""
        self.create_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []

    def create_run(self, **kwargs: Any) -> str:
        """Record run creation call.

        Args:
            **kwargs: Arguments supplied to create_run.

        Returns:
            A fake run identifier.
        """
        self.create_calls.append(kwargs)
        return f"run-{len(self.create_calls)}"

    def update_run(self, **kwargs: Any) -> None:
        """Record run update call.

        Args:
            **kwargs: Arguments supplied to update_run.
        """
        self.update_calls.append(kwargs)


class RecordingSpan:
    """Span double recording all set attributes and events."""

    def __init__(self, name: str) -> None:
        """Initialize span double.

        Args:
            name: Span operation name.
        """
        self.name = name
        self.attributes: dict[str, Any] = {}
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.ended = False

    def set_attribute(self, key: str, value: Any) -> None:
        """Record attribute.

        Args:
            key: Attribute name.
            value: Attribute value.
        """
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any]) -> None:
        """Record span event.

        Args:
            name: Event name.
            attributes: Event attributes.
        """
        self.events.append((name, attributes))

    def end(self) -> None:
        """Mark span completed."""
        self.ended = True

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        """Record status update."""


class RecordingTracer:
    """Tracer double tracking created spans."""

    def __init__(self) -> None:
        """Initialize tracer."""
        self.spans: list[RecordingSpan] = []

    def start_span(self, name: str) -> RecordingSpan:
        """Create and track a span double.

        Args:
            name: Span operation name.

        Returns:
            The recording span double.
        """
        span = RecordingSpan(name)
        self.spans.append(span)
        return span


@runtime_tool(name="calc_add", description="Add numbers.", permission="calc.add")
async def _calc_add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b


@pytest.mark.asyncio
async def test_controlled_turn_does_not_leak_canary_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify controlled_turn execution never exposes the canary thread ID in any public surface."""
    sdk = CanarySDK()
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread(*args: Any, **kwargs: Any) -> FakeThread:
        return FakeThread(sdk, thread_id=CANARY_THREAD_ID)

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread,
    )

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    registry = ToolRegistry()
    registry.register(_calc_add)
    model = runtime.model(profile="controlled_turn", level="low").with_tools(registry)

    # 1. Direct ainvoke
    result = await model.ainvoke("hello world")
    assert result.output == "ok"
    assert result.session_id is None
    assert result.task_id is None
    assert_no_canary_leak(result)

    # 2. Streaming astream
    stream_events: list[RuntimeEvent] = []
    async for event in model.astream("hello stream"):
        stream_events.append(event)
        assert_no_canary_leak(event)
        assert "thread_id" not in event.metadata

    # 3. Check all runtime-level emitted events
    for event in runtime.events:
        assert_no_canary_leak(event)
        assert "thread_id" not in event.metadata

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_agent_task_does_not_leak_canary_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify controlled_agent multi-turn task execution never exposes the canary thread ID."""
    sdk = CanarySDK()
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread(*args: Any, **kwargs: Any) -> FakeThread:
        return FakeThread(sdk, thread_id=CANARY_THREAD_ID)

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread,
    )

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    registry = ToolRegistry()
    registry.register(_calc_add)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
    )

    task = await runtime.task("controlled_agent", registry=registry, executor=executor)
    assert task.id.startswith("task_")

    # Turn 1
    res1 = await task.ainvoke("calculate turn 1")
    assert res1.task_id == task.id
    assert res1.session_id is None
    assert_no_canary_leak(res1)

    # Turn 2 with streaming
    turn2_events: list[RuntimeEvent] = []
    async for event in task.astream("calculate turn 2"):
        turn2_events.append(event)
        assert_no_canary_leak(event)
        assert "thread_id" not in event.metadata
        assert event.session_id is None

    # Check all events in runtime
    for event in runtime.events:
        assert_no_canary_leak(event)
        assert "thread_id" not in event.metadata
        assert event.session_id is None

    # Check tool executor events
    for event in executor.events:
        assert_no_canary_leak(event)
        assert "thread_id" not in event.metadata
        assert event.session_id is None

    await task.close()
    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_event_bus_filters_thread_id_across_all_payload_modes() -> None:
    """Verify RuntimeEventBus excludes thread_id under FULL, METADATA_ONLY, and REDACTED modes."""
    for mode in (PayloadMode.FULL, PayloadMode.METADATA_ONLY, PayloadMode.REDACTED):
        observer = RecordingObserver()
        bus = RuntimeEventBus(
            ObservabilityConfig(observers=(ObserverBinding(cast(RuntimeObserver, observer), mode),))
        )

        # Inject an event with canary thread_id in metadata
        event = RuntimeEvent(
            kind=RuntimeEventKind.INVOCATION_STARTED,
            event_id="test:1",
            sequence=1,
            occurred_at=datetime.now(UTC),
            runtime=RuntimeIdentity("codex", "test"),
            invocation_id="inv-1",
            task_id="task_123",
            metadata={
                "safe_key": "safe_value",
                "thread_id": CANARY_THREAD_ID,
                "provider_thread_id": CANARY_THREAD_ID,
                "provider_thread": CANARY_THREAD_ID,
            },
        )
        await bus.emit(event)

        assert len(observer.events) == 1
        projected = observer.events[0]
        assert "thread_id" not in projected.metadata
        assert "provider_thread_id" not in projected.metadata
        assert "provider_thread" not in projected.metadata
        assert projected.metadata.get("safe_key") == "safe_value"
        assert_no_canary_leak(projected)


@pytest.mark.asyncio
async def test_langsmith_observer_filters_canary_thread_id() -> None:
    """Verify LangSmithObserver never includes canary thread IDs in run metadata."""
    client = RecordingLangSmithClient()
    observer = LangSmithObserver(client)

    event = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="test:1",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime=RuntimeIdentity("codex", "test"),
        invocation_id="inv-1",
        task_id="task_123",
        metadata={
            "safe_key": "safe_value",
            "thread_id": CANARY_THREAD_ID,
            "provider_thread_id": CANARY_THREAD_ID,
        },
    )
    await observer.on_event(event)

    assert len(client.create_calls) == 1
    create_call = client.create_calls[0]
    extra_metadata = create_call.get("extra", {}).get("metadata", {})
    assert "thread_id" not in extra_metadata
    assert "provider_thread_id" not in extra_metadata
    assert extra_metadata.get("safe_key") == "safe_value"
    assert extra_metadata.get("proteo_task_id") == "task_123"
    assert_no_canary_leak(create_call)


@pytest.mark.asyncio
async def test_opentelemetry_observer_never_records_canary_thread_id() -> None:
    """Verify OpenTelemetryObserver never sets canary thread attributes on spans."""
    tracer = RecordingTracer()
    observer = OpenTelemetryObserver(tracer, object())

    event = RuntimeEvent(
        kind=RuntimeEventKind.INVOCATION_STARTED,
        event_id="test:1",
        sequence=1,
        occurred_at=datetime.now(UTC),
        runtime=RuntimeIdentity("codex", "test"),
        invocation_id="inv-1",
        task_id="task_123",
        metadata={
            "model": "gpt-5.6-terra",
            "profile": "controlled_agent",
            "thread_id": CANARY_THREAD_ID,
        },
    )
    await observer.on_event(event)

    assert len(tracer.spans) > 0
    for span in tracer.spans:
        assert "thread_id" not in span.attributes
        assert "proteo.thread_id" not in span.attributes
        assert_no_canary_leak(span.attributes)


@pytest.mark.asyncio
async def test_langgraph_node_stream_projection_never_leaks_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify RuntimeNode streaming projection excludes thread_id from LangGraph envelopes."""
    sdk = CanarySDK()
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread(*args: Any, **kwargs: Any) -> FakeThread:
        return FakeThread(sdk, thread_id=CANARY_THREAD_ID)

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread,
    )

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    registry = ToolRegistry()
    registry.register(_calc_add)
    model = runtime.model(profile="controlled_turn", level="low").with_tools(registry)
    node: RuntimeNode[dict[str, Any]] = RuntimeNode(model)

    projected_items: list[dict[str, Any]] = []

    def fake_stream_writer(item: Any) -> None:
        projected_items.append(item)

    monkeypatch.setattr(
        "proteo_runtime.integrations.langgraph.node.get_stream_writer",
        lambda: fake_stream_writer,
    )

    output = await node({"input": "test message"})
    assert output == {"output": "ok"}
    assert len(projected_items) > 0

    for envelope in projected_items:
        assert envelope.get("type") == "proteo_runtime_event"
        event_data = envelope.get("event", {})
        metadata = event_data.get("metadata", {})
        assert "thread_id" not in metadata
        assert_no_canary_leak(envelope)

    await runtime.close()


@pytest.mark.asyncio
async def test_codex_tool_mux_and_bridge_use_canary_internally_without_public_leak() -> None:
    """Verify CodexToolMux routes via canary internally while keeping ToolRequest neutral."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
    )

    bridge = CodexToolBridge(executor, invocation_id="inv-canary")
    mux = CodexToolMux()
    mux.register(bridge, thread_id=CANARY_THREAD_ID, turn_id="turn-canary")

    # Mux route matching uses CANARY_THREAD_ID internally
    response = await asyncio.to_thread(
        mux,
        "item/tool/call",
        {
            "invocationId": "inv-canary",
            "threadId": CANARY_THREAD_ID,
            "turnId": "turn-canary",
            "callId": "call-1",
            "name": "calc_add",
            "arguments": {"a": 2, "b": 3},
        },
    )
    assert response["success"] is True
    output_data = json.loads(response["contentItems"][0]["text"])
    assert output_data["success"] is True
    assert output_data["output"] == 5

    # Check that executor events NEVER contain CANARY_THREAD_ID and session_id is None
    assert len(executor.events) >= 3
    for event in executor.events:
        assert event.session_id is None
        assert "thread_id" not in event.metadata
        assert_no_canary_leak(event)

    mux.unregister(bridge)


@pytest.mark.asyncio
async def test_session_turn_does_not_leak_canary_thread_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify persistent session turns never expose the underlying raw thread ID."""
    sdk = CanarySDK()
    install_sdk(monkeypatch, sdk)

    runtime = CodexRuntime()
    await runtime.start()

    session = await runtime.session("session", level="low")

    res = await session.ainvoke("hello in session")
    assert res.output == "ok"
    assert res.session_id == session.id
    assert_no_canary_leak(res)

    for event in runtime.events:
        assert_no_canary_leak(event)
        assert "thread_id" not in event.metadata

    await session.close()
    await runtime.close()


def test_canary_detector_raises_on_leak() -> None:
    """Verify that assert_no_canary_leak correctly detects leaks and fails fast."""
    # Leaked in string
    with pytest.raises(AssertionError, match="Canary leaked into string"):
        assert_no_canary_leak(f"prefix-{CANARY_THREAD_ID}")

    # Leaked in dict value
    with pytest.raises(AssertionError, match="Canary leaked into string"):
        assert_no_canary_leak({"meta": {"key": CANARY_THREAD_ID}})

    # Leaked in dict key
    with pytest.raises(AssertionError, match="Canary leaked into mapping key"):
        assert_no_canary_leak({CANARY_THREAD_ID: "value"})

    # Leaked in dataclass
    result = RuntimeResult(
        output="test",
        usage=RuntimeUsage(total_tokens=1),
        runtime=RuntimeIdentity("codex", "test"),
        model="gpt-5.6-terra",
        profile="controlled_turn",
        session_id=CANARY_THREAD_ID,
    )
    with pytest.raises(AssertionError, match="Canary leaked into string"):
        assert_no_canary_leak(result)
