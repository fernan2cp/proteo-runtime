"""Deterministic fake runtime behavior tests."""

import asyncio

import pytest

from proteo_runtime import RuntimeInput
from proteo_runtime.core.errors import InterruptedError, SessionBusyError, SessionNotFoundError
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
