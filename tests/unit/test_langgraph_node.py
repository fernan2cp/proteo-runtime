"""Unit tests for the optional LangGraph RuntimeNode adapter."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from proteo_runtime import (
    CancellationError,
    ConfigurationError,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeIdentity,
    RuntimeUnavailableError,
)
from proteo_runtime.core.input import RuntimeInput
from proteo_runtime.core.model import InvocationConfig, RuntimeModel, RuntimeResult
from proteo_runtime.core.runtime import Runtime
from proteo_runtime.integrations import langgraph as langgraph_integration
from proteo_runtime.integrations.langgraph import node as node_module
from proteo_runtime.testing import FakeRuntime, FakeTurn
from proteo_runtime.tools import ToolRegistry, runtime_tool


class Decision(BaseModel):
    """Structured value used by adapter tests."""

    decision: str


class _TrackingSession:
    """Forward a fake session while recording lifecycle calls."""

    def __init__(self, inner: Any) -> None:
        """Initialize the tracking wrapper around a session handle."""

        self._inner = inner
        self.close_calls = 0
        self.interrupt_calls = 0
        self.archive_calls = 0
        self.delete_calls = 0

    @property
    def descriptor(self) -> str:
        """Return the wrapped opaque descriptor."""

        return cast(str, self._inner.descriptor)

    async def ainvoke(self, input: Any, **kwargs: Any) -> Any:
        """Delegate direct invocation to the wrapped session."""

        return await self._inner.ainvoke(input, **kwargs)

    def astream(self, input: Any, **kwargs: Any) -> AsyncIterator[RuntimeEvent]:
        """Delegate event streaming to the wrapped session."""

        return cast(AsyncIterator[RuntimeEvent], self._inner.astream(input, **kwargs))

    async def interrupt(self) -> None:
        """Record and delegate an interruption request."""

        self.interrupt_calls += 1
        await self._inner.interrupt()

    async def close(self) -> None:
        """Record and delegate local handle cleanup."""

        self.close_calls += 1
        await self._inner.close()

    async def archive(self) -> None:
        """Record and delegate archive operations."""

        self.archive_calls += 1
        await self._inner.archive()

    async def delete(self) -> None:
        """Record and delegate delete operations."""

        self.delete_calls += 1
        await self._inner.delete()


class _ClosableStream:
    """Async iterator that records exactly how often it is closed."""

    def __init__(self, events: tuple[RuntimeEvent, ...], *, block: bool = False) -> None:
        """Initialize the scripted event sequence."""

        self._events = iter(events)
        self._gate = asyncio.Event() if block else None
        self.close_calls = 0

    def __aiter__(self) -> _ClosableStream:
        """Return this iterator for asynchronous iteration."""

        return self

    async def __anext__(self) -> RuntimeEvent:
        """Return the next event or finish the stream."""

        if self._gate is not None:
            await self._gate.wait()
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Record one adapter-requested iterator close."""

        self.close_calls += 1


def _writer(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Install a deterministic custom stream writer for direct node calls."""

    events: list[dict[str, Any]] = []
    monkeypatch.setattr(node_module, "get_stream_writer", lambda: events.append)
    return events


@pytest.mark.asyncio
async def test_runtime_node_default_mapping_and_structured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default keys return only the neutral value, including structured values."""

    events = _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(value='{"decision":"yes"}')])
    model = runtime.model(profile="brain").with_structured_output(Decision)

    result = await langgraph_integration.RuntimeNode[Any](model)({"input": "choose"})

    assert isinstance(result["output"], Decision)
    assert result["output"].decision == "yes"
    assert all("result" not in event["event"] for event in events)


@pytest.mark.asyncio
async def test_runtime_node_custom_mappers_copy_state_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom mappers can use arbitrary state while returning a copied update."""

    _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(value="answer")])
    node = langgraph_integration.RuntimeNode[Any](
        runtime.model(profile="brain"),
        input_mapper=lambda state: state["question"],
        output_mapper=lambda result: {"answer": result.value, "usage": result.usage.total_tokens},
    )

    result = await node({"question": "what?"})

    assert result == {"answer": "answer", "usage": None}
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_runtime_node_rejects_missing_input_and_session_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid default state and persistent configuration fail before provider work."""

    _writer(monkeypatch)
    runtime = FakeRuntime()
    with pytest.raises(ConfigurationError, match="input key"):
        await langgraph_integration.RuntimeNode[Any](runtime.model(profile="brain"))({})
    with pytest.raises(ConfigurationError, match="requires a non-empty session descriptor"):
        await langgraph_integration.RuntimeNode[Any](cast(Runtime, runtime))({"input": "work"})


def test_runtime_node_constructor_and_projection_security() -> None:
    """Constructor and event projection reject unsafe or resumable data exposure."""

    with pytest.raises(ValueError):
        langgraph_integration.RuntimeNode[Any](cast(Runtime, FakeRuntime()), input_key="")
    event = RuntimeEvent(
        RuntimeEventKind.OUTPUT_TEXT_DELTA,
        "event-1",
        0,
        datetime.now(UTC),
        RuntimeIdentity("fake", "fingerprint"),
        session_id="prt1.secret-descriptor",
        metadata={"nested": {"token": "secret"}, "text": "api_key=secret-value"},
    )

    projected = node_module._project_event(event)

    assert projected["event"]["session_correlation_id"].startswith("sha256:")
    assert "prt1.secret-descriptor" not in json.dumps(projected)
    assert "token" not in json.dumps(projected)
    assert "secret-value" not in json.dumps(projected)
    json.dumps(projected)


def test_runtime_node_rejects_non_executor_and_projects_json_shapes() -> None:
    """Reject an unrecognised executor and normalize all supported JSON shapes."""

    with pytest.raises(TypeError, match="exactly one"):
        langgraph_integration.RuntimeNode[Any](cast(Any, object()))
    assert node_module._project_json({"values": (1, 2), "set": {"a"}, "nan": math.nan}) == {
        "values": [1, 2],
        "set": ["a"],
        "nan": None,
    }
    assert node_module._project_json(object()) is None
    assert node_module._session_correlation_id(None) is None
    assert node_module._configurable(None) == {}


def test_invocation_config_allowlist_and_validation() -> None:
    """Keep only approved metadata and reject unsafe or non-JSON values."""

    config = cast(
        RunnableConfig,
        {
            "metadata": {
                "proteo": {"nested": [1, {"ok": True}]},
                "langgraph_node": "proteo",
                "langgraph_step": 2,
                "unknown": "ignored",
            },
            "tags": ["safe"],
            "run_id": "run-1",
            "configurable": {"other": "ignored"},
            "callbacks": object(),
        },
    )
    invocation = node_module._invocation_config(config)
    assert invocation.metadata["proteo"]["nested"][1]["ok"] is True
    assert invocation.metadata["langgraph"] == {
        "langgraph_node": "proteo",
        "langgraph_step": 2,
    }
    assert invocation.metadata["langgraph_tags"] == ("safe",)
    assert invocation.metadata["langgraph_run_id"] == "run-1"
    invalid = [
        {"metadata": []},
        {"metadata": {"proteo": []}},
        {"metadata": {"proteo": {"token": "secret"}}},
        {"metadata": {"proteo": {"value": object()}}},
        {"metadata": {"proteo": {"value": math.inf}}},
        {"tags": "not-a-list"},
        {"tags": ["safe", object()]},
    ]
    for raw in invalid:
        with pytest.raises(ConfigurationError):
            node_module._invocation_config(cast(RunnableConfig, raw))
    with pytest.raises(ConfigurationError, match="configurable"):
        node_module._configurable(cast(RunnableConfig, {"configurable": []}))


@pytest.mark.asyncio
async def test_runtime_node_forwards_only_safe_invocation_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass a copied allowlisted InvocationConfig to the model stream."""

    _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(value="answer")])
    model = runtime.model(profile="brain")
    captured: list[InvocationConfig | None] = []
    original = model.astream

    def capture(
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Capture the config and delegate to the deterministic model."""

        captured.append(config)
        return original(input, config=config, include_raw=include_raw)

    monkeypatch.setattr(cast(Any, model), "astream", capture)
    original_config: dict[str, Any] = {
        "metadata": {"proteo": {"request": "one"}, "langgraph_node": "node"},
        "tags": ["tag"],
        "run_id": "run",
        "configurable": {"thread_id": "thread"},
    }
    result = await langgraph_integration.RuntimeNode[Any](model)(
        {"input": "question"}, cast(RunnableConfig, original_config)
    )
    assert result == {"output": "answer"}
    assert captured and captured[0] is not None
    captured_config = captured[0]
    assert captured_config is not None
    assert captured_config.metadata["proteo"] == {"request": "one"}
    assert original_config["metadata"]["proteo"] == {"request": "one"}


@pytest.mark.asyncio
async def test_runtime_node_preserves_provider_cancellation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve provider cancellation when the caller task is not cancelling."""

    _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(error=CancellationError("cancelled"))])
    with pytest.raises(CancellationError, match="cancelled"):
        await langgraph_integration.RuntimeNode[Any](runtime.model(profile="brain"))(
            {"input": "cancel"}
        )


@pytest.mark.asyncio
async def test_runtime_node_rejects_descriptor_and_invalid_state_or_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject mixed model/session configuration and malformed mapper boundaries."""

    _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(value="answer")])
    model = runtime.model(profile="brain")
    node = langgraph_integration.RuntimeNode[Any](model)
    with pytest.raises(ConfigurationError, match="not accepted"):
        await node(
            {"input": "question"},
            cast(RunnableConfig, {"configurable": {"proteo_session_id": "descriptor"}}),
        )
    with pytest.raises(TypeError, match="Mapping"):
        await node(cast(Any, "not-a-state"))
    bad_output = langgraph_integration.RuntimeNode[Any](
        runtime.model(profile="brain"), output_mapper=lambda result: cast(Any, [result.value])
    )
    with pytest.raises(TypeError, match="output_mapper"):
        await bad_output({"input": "question"})


@pytest.mark.asyncio
async def test_runtime_node_terminal_state_machine_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject EOF and duplicate successful terminal events."""

    _writer(monkeypatch)
    identity = RuntimeIdentity("fake", "fingerprint")
    result = RuntimeResult(output="done", runtime=identity)
    terminal = RuntimeEvent(
        RuntimeEventKind.INVOCATION_COMPLETED,
        "terminal",
        1,
        datetime.now(UTC),
        identity,
        result=result,
    )

    async def eof() -> AsyncIterator[RuntimeEvent]:
        """Yield no events."""

        events: tuple[RuntimeEvent, ...] = ()
        for event in events:
            yield event

    async def duplicate() -> AsyncIterator[RuntimeEvent]:
        """Yield two successful terminals."""

        yield terminal
        yield terminal

    with pytest.raises(RuntimeUnavailableError, match="ended"):
        await langgraph_integration.RuntimeNode[Any](cast(RuntimeModel[Any], _StreamModel(eof)))(
            {"input": "question"}
        )
    with pytest.raises(RuntimeUnavailableError, match="multiple"):
        await langgraph_integration.RuntimeNode[Any](
            cast(RuntimeModel[Any], _StreamModel(duplicate))
        )({"input": "question"})


@pytest.mark.asyncio
async def test_runtime_node_closes_stream_exactly_once_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful consumption closes the runtime iterator exactly once."""

    _writer(monkeypatch)
    identity = RuntimeIdentity("fake", "fingerprint")
    terminal = RuntimeEvent(
        RuntimeEventKind.INVOCATION_COMPLETED,
        "terminal",
        1,
        datetime.now(UTC),
        identity,
        result=RuntimeResult(output="done", runtime=identity),
    )
    stream = _ClosableStream((terminal,))
    model = _StreamModel(lambda: stream)

    result = await langgraph_integration.RuntimeNode[Any](cast(RuntimeModel[Any], model))(
        {"input": "question"}
    )

    assert result == {"output": "done"}
    assert stream.close_calls == 1


@pytest.mark.asyncio
async def test_runtime_node_closes_stream_exactly_once_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller cancellation closes a blocked runtime iterator exactly once."""

    _writer(monkeypatch)
    stream = _ClosableStream((), block=True)
    model = _StreamModel(lambda: stream)
    task = asyncio.create_task(
        langgraph_integration.RuntimeNode[Any](cast(RuntimeModel[Any], model))(
            {"input": "question"}
        )
    )
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.close_calls == 1


class _StreamModel:
    """Minimal model-shaped stream provider for terminal state tests."""

    def __init__(self, factory: Callable[[], AsyncIterator[RuntimeEvent]]) -> None:
        """Store the async event factory."""

        self._factory = factory

    def astream(self, input: Any, **kwargs: Any) -> AsyncIterator[RuntimeEvent]:
        """Return the scripted event stream."""

        del input, kwargs
        return self._factory()

    async def ainvoke(self, input: Any, **kwargs: Any) -> RuntimeResult[Any]:
        """Satisfy the model protocol without being called."""

        del input, kwargs
        raise AssertionError("ainvoke must not be selected")

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Return self for protocol completeness."""

        del schema, kwargs
        return self

    async def effective_capabilities(self) -> Any:
        """Return no-op capabilities for protocol completeness."""

        return await FakeRuntime().capabilities()


@pytest.mark.asyncio
async def test_runtime_node_resumes_and_closes_session_without_leaking_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session mode resumes one handle and keeps the raw descriptor out of events/state."""

    events = _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(value="session answer")])
    created = await runtime.session()
    descriptor = created.descriptor
    await created.close()

    result = await langgraph_integration.RuntimeNode[Any](cast(Runtime, runtime))(
        {"input": "continue"},
        {"configurable": {"proteo_session_id": descriptor}},
    )

    assert result == {"output": "session answer"}
    serialized_events = json.dumps(events)
    assert descriptor not in serialized_events
    assert any(event["event"]["session_correlation_id"] for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "runtime_error", "mapper_error", "cancelled"])
async def test_runtime_node_session_cleanup_is_single_and_non_destructive(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """Session handles close once without interruption or destructive operations."""

    _writer(monkeypatch)
    turn = FakeTurn(value="answer", delay_seconds=0.2 if outcome == "cancelled" else 0)
    if outcome == "runtime_error":
        turn = FakeTurn(error=RuntimeUnavailableError("scripted failure"))
    runtime = FakeRuntime(turns=[turn])
    created = await runtime.session()
    descriptor = created.descriptor
    await created.close()
    original_resume = runtime.resume_session
    tracked: list[_TrackingSession] = []

    def mapper_error(result: RuntimeResult[Any]) -> Mapping[str, Any]:
        """Raise a host mapper error after the runtime terminal event."""

        del result
        raise ValueError("mapper failure")

    async def resume(session_id: str) -> _TrackingSession:
        """Resume and wrap one host-owned session handle."""

        handle = _TrackingSession(await original_resume(session_id))
        tracked.append(handle)
        return handle

    monkeypatch.setattr(runtime, "resume_session", resume)
    node = langgraph_integration.RuntimeNode[Any](
        cast(Runtime, runtime),
        output_mapper=mapper_error if outcome == "mapper_error" else None,
    )

    call = node(
        {"input": "continue"},
        {"configurable": {"proteo_session_id": descriptor}},
    )
    if outcome == "cancelled":
        task = asyncio.create_task(call)
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif outcome == "runtime_error":
        with pytest.raises(RuntimeUnavailableError, match="scripted failure"):
            await call
    elif outcome == "mapper_error":
        with pytest.raises(ValueError, match="mapper failure"):
            await call
    else:
        assert await call == {"output": "answer"}

    assert len(tracked) == 1
    assert tracked[0].close_calls == 1
    assert tracked[0].interrupt_calls == 0
    assert tracked[0].archive_calls == 0
    assert tracked[0].delete_calls == 0
    assert all(not state.active for state in runtime._sessions.values())


@pytest.mark.asyncio
async def test_runtime_node_restores_task_cancellation_after_provider_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled LangGraph task surfaces CancelledError after provider cleanup."""

    _writer(monkeypatch)
    runtime = FakeRuntime(turns=[FakeTurn(delay_seconds=0.2)])
    task = asyncio.create_task(
        langgraph_integration.RuntimeNode[Any](runtime.model(profile="brain"))({"input": "wait"})
    )
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runtime_node_rejects_invalid_terminal_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """A completed event without a neutral result cannot fabricate state."""

    _writer(monkeypatch)
    runtime = FakeRuntime()
    node = langgraph_integration.RuntimeNode[Any](runtime.model(profile="brain"))
    event = RuntimeEvent(
        RuntimeEventKind.INVOCATION_COMPLETED,
        "event-1",
        0,
        datetime.now(UTC),
        RuntimeIdentity("fake", "fingerprint"),
    )

    async def events() -> Any:
        """Yield one malformed terminal event."""

        yield event

    class MalformedModel:
        """RuntimeModel-shaped executor with a malformed stream."""

        async def ainvoke(self, input: Any, **kwargs: Any) -> Any:
            """Provide the required protocol method."""

            del input, kwargs
            raise AssertionError("ainvoke must not be selected")

        def astream(self, input: Any, **kwargs: Any) -> Any:
            """Return the malformed event stream."""

            del input, kwargs
            return events()

        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            """Provide the required protocol method."""

            del schema, kwargs
            return self

        async def effective_capabilities(self) -> Any:
            """Provide the required protocol method."""

            return await runtime.capabilities()

    node = langgraph_integration.RuntimeNode[Any](cast(RuntimeModel[Any], MalformedModel()))
    with pytest.raises(RuntimeUnavailableError, match="without a result"):
        await node({"input": "invalid"})


@runtime_tool(name="dummy_tool", description="A dummy tool for testing.", permission="dummy.perm")
async def _dummy_node_tool(val: int) -> int:
    """Return an integer value.

    Args:
        val: Input value.

    Returns:
        The same value.
    """
    return val


@pytest.mark.asyncio
async def test_runtime_node_routes_to_active_task_via_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify RuntimeNode dispatches to active task using proteo_task_id."""
    events = _writer(monkeypatch)
    registry = ToolRegistry()
    registry.register(_dummy_node_tool)
    runtime = FakeRuntime(turns=[FakeTurn(value="task output")])
    task = await runtime.task("controlled_agent", registry=registry)
    node = langgraph_integration.RuntimeNode[dict[str, Any]](cast(Runtime, runtime))
    result = await node(
        {"input": "hello task"},
        config={"configurable": {"proteo_task_id": task.id}},
    )
    assert result == {"output": "task output"}
    assert any(e.get("event", {}).get("task_id") == task.id for e in events)
    await task.close()


@pytest.mark.asyncio
async def test_runtime_node_rejects_conflicting_task_and_session_ids() -> None:
    """Verify RuntimeNode rejects conflicting proteo_task_id and proteo_session_id."""
    runtime = FakeRuntime()
    node = langgraph_integration.RuntimeNode[dict[str, Any]](cast(Runtime, runtime))
    with pytest.raises(
        ConfigurationError,
        match="Cannot specify both proteo_task_id and proteo_session_id",
    ):
        await node(
            {"input": "conflict"},
            config={
                "configurable": {
                    "proteo_task_id": "task_123",
                    "proteo_session_id": "session_123",
                }
            },
        )


@pytest.mark.asyncio
async def test_model_node_rejects_task_id() -> None:
    """Verify a model-backed RuntimeNode rejects proteo_task_id."""
    runtime = FakeRuntime()
    model = runtime.model(profile="brain")
    node = langgraph_integration.RuntimeNode[dict[str, Any]](model)
    with pytest.raises(
        ConfigurationError,
        match="Task identifiers are not accepted by a model node",
    ):
        await node(
            {"input": "test"},
            config={"configurable": {"proteo_task_id": "task_123"}},
        )


@pytest.mark.asyncio
async def test_runtime_node_rejects_empty_task_id() -> None:
    """Verify RuntimeNode rejects empty proteo_task_id."""
    runtime = FakeRuntime()
    node = langgraph_integration.RuntimeNode[dict[str, Any]](cast(Runtime, runtime))
    with pytest.raises(
        ConfigurationError,
        match="non-empty task identifier",
    ):
        await node(
            {"input": "test"},
            config={"configurable": {"proteo_task_id": "   "}},
        )
