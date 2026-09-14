"""Deterministic fake runtime behavior tests."""

import asyncio
from collections.abc import AsyncGenerator
from typing import cast

import pytest

from proteo_runtime import RuntimeEvent, RuntimeEventKind, RuntimeInput
from proteo_runtime.core.errors import (
    AuthenticationError,
    CancellationError,
    CapabilityError,
    InterruptedError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
    SessionBusyError,
    SessionNotFoundError,
)
from proteo_runtime.testing import FakeRuntime, FakeTurn


@pytest.mark.asyncio
async def test_fake_lifecycle_invoke_stream_resume_archive_delete() -> None:
    """Fake runtime supports lifecycle, ordered stream events, and sessions."""

    runtime = FakeRuntime(turns=[FakeTurn(value="hello world")])
    await runtime.start()
    result = await runtime.model(profile="brain").ainvoke(RuntimeInput.from_value("hi"))
    assert result.value == "hello world"
    session = await runtime.session()
    stream = [event async for event in session.astream(RuntimeInput.from_value("hi"))]
    assert [event.sequence for event in stream] == sorted(event.sequence for event in stream)
    kinds = [event.kind for event in stream]
    assert kinds.index(RuntimeEventKind.OUTPUT_TEXT_DELTA) < kinds.index(
        RuntimeEventKind.TOKEN_USAGE_UPDATED
    )
    assert kinds.index(RuntimeEventKind.TOKEN_USAGE_UPDATED) < kinds.index(
        RuntimeEventKind.TURN_COMPLETED
    )
    assert not session._state.active
    await session.archive()
    await session.close()
    resumed = await runtime.resume_session(session.id)
    await resumed.delete()
    with pytest.raises(SessionNotFoundError):
        await runtime.resume_session(session.id)
    await runtime.close()


@pytest.mark.asyncio
async def test_fake_busy_interrupt_and_scripted_error() -> None:
    """Concurrent turns fail atomically and interruption clears active state."""

    runtime = FakeRuntime(
        turns=[
            FakeTurn(value="slow", delay_seconds=0.05),
            FakeTurn(error=SessionBusyError("script")),
        ]
    )
    session = await runtime.session()
    first = asyncio.create_task(session.ainvoke(RuntimeInput.from_value("a")))
    await asyncio.sleep(0)
    with pytest.raises(SessionBusyError):
        await session.ainvoke(RuntimeInput.from_value("b"))
    await session.interrupt()
    with pytest.raises(InterruptedError):
        await first
    assert not session._state.active


@pytest.mark.asyncio
async def test_fake_runtime_context_manager_is_idempotent() -> None:
    """Async context management starts and stops the runtime once."""

    runtime = FakeRuntime()
    async with runtime as active:
        assert active is runtime
        await runtime.start()
    await runtime.close()
    assert [event.kind for event in runtime.events] == [
        RuntimeEventKind.RUNTIME_STARTED,
        RuntimeEventKind.RUNTIME_STOPPED,
    ]


@pytest.mark.asyncio
async def test_session_stream_close_releases_lock_and_allows_next_turn() -> None:
    """Closing a partially consumed stream releases its active-turn claim."""

    runtime = FakeRuntime(turns=[FakeTurn(value="first"), FakeTurn(value="second")])
    session = await runtime.session()
    stream = cast(
        AsyncGenerator[RuntimeEvent, None], session.astream(RuntimeInput.from_value("first"))
    )
    first = await anext(stream)
    assert first.kind is RuntimeEventKind.INVOCATION_STARTED
    assert bool(session._state.active)
    await stream.aclose()
    assert session._state.active is False
    next_result = await session.ainvoke(RuntimeInput.from_value("next"))
    assert next_result.value == "second"


@pytest.mark.asyncio
async def test_fake_errors_are_preserved_or_sanitized() -> None:
    """Known errors pass through while provider-like errors lose secret text."""

    for error in (
        AuthenticationError("auth"),
        CapabilityError("capability"),
        RuntimeTimeoutError("timeout"),
    ):
        runtime = FakeRuntime(turns=[FakeTurn(error=error)])
        with pytest.raises(type(error)):
            await runtime.model(profile="brain").ainvoke(RuntimeInput.from_value("input"))
    runtime = FakeRuntime(turns=[FakeTurn(error=ValueError("api_key=secret"))])
    with pytest.raises(RuntimeUnavailableError) as exc:
        await runtime.model(profile="brain").ainvoke(RuntimeInput.from_value("input"))
    assert "secret" not in str(exc.value)
    assert "secret" not in repr(exc.value.details)


@pytest.mark.asyncio
async def test_session_stream_cancellation_releases_lock() -> None:
    """Cancelling a delayed stream clears its active-turn claim."""

    runtime = FakeRuntime(turns=[FakeTurn(delay_seconds=0.2)])
    session = await runtime.session()
    stream = cast(
        AsyncGenerator[RuntimeEvent, None], session.astream(RuntimeInput.from_value("wait"))
    )
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(CancellationError):
        await task
    assert session._state.active is False


@pytest.mark.asyncio
async def test_busy_stream_does_not_release_other_turn() -> None:
    """A rejected concurrent stream leaves the first turn active."""

    runtime = FakeRuntime(turns=[FakeTurn(delay_seconds=0.05)])
    session = await runtime.session()
    first = asyncio.create_task(session.ainvoke(RuntimeInput.from_value("first")))
    await asyncio.sleep(0.01)
    busy_stream = cast(
        AsyncGenerator[RuntimeEvent, None], session.astream(RuntimeInput.from_value("second"))
    )
    with pytest.raises(SessionBusyError):
        await anext(busy_stream)
    assert session._state.active
    await session.interrupt()
    with pytest.raises(InterruptedError):
        await first
