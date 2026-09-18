"""Unit tests verifying ToolExecutor lifecycle and turn-scoped cleanup in controlled_turn.

Verifies that invocation-scoped controlled_turn executions clean up mux routes,
invocation deduplication state, and locks in ToolExecutor across success,
failure, timeout, cancellation, and early stream closure.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from proteo_runtime.core.errors import (
    CancellationError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
)
from proteo_runtime.core.events import RuntimeEvent
from proteo_runtime.core.model import InvocationConfig
from proteo_runtime.providers.codex.runtime import CodexRuntime, _CodexModel
from proteo_runtime.tools import (
    ToolExecutor,
    ToolPermissionPolicy,
    ToolRegistry,
    ToolSnapshot,
    runtime_tool,
)

# Ensure tests/unit is available for imports
_unit_dir = str(Path(__file__).resolve().parent.parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import (  # noqa: E402
    FakeSDK,
    FakeThread,
    FakeTurn,
    _notifications,
    install_sdk,
)


@runtime_tool(name="calc_add", description="Add two integers.", permission="calc.add")
async def _calc_add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First integer.
        b: Second integer.

    Returns:
        Sum of the numbers.
    """
    return a + b


class SpyToolExecutor(ToolExecutor):
    """ToolExecutor test spy tracking end_invocation calls and recording invocations."""

    def __init__(
        self,
        *args: Any,
        ended_invocations: list[str] | None = None,
        shared_calls: dict[tuple[str, str], asyncio.Future[Any]] | None = None,
        shared_locks: dict[str, asyncio.Lock] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize spy with tracking lists and shared state.

        Args:
            *args: Positional arguments forwarded to ToolExecutor.
            ended_invocations: Optional shared list tracking ended invocation IDs.
            shared_calls: Optional shared deduplication calls dictionary.
            shared_locks: Optional shared locks dictionary.
            **kwargs: Keyword arguments forwarded to ToolExecutor.
        """
        super().__init__(*args, **kwargs)
        self.ended_invocations: list[str] = (
            ended_invocations if ended_invocations is not None else []
        )
        if shared_calls is not None:
            self._calls = shared_calls
        if shared_locks is not None:
            self._locks = shared_locks

    def clone(
        self,
        *,
        snapshot: ToolSnapshot | None = None,
        permission_policy: ToolPermissionPolicy | None = None,
        freeze: bool = False,
        share_events: bool = True,
    ) -> ToolExecutor:
        """Clone while sharing ended_invocations, _calls, and _locks.

        Args:
            snapshot: Optional ToolSnapshot override.
            permission_policy: Optional ToolPermissionPolicy override.
            freeze: Whether to freeze the cloned executor against future mutation.
            share_events: Whether to share event logs.

        Returns:
            Cloned SpyToolExecutor instance sharing tracking state.
        """
        cloned = super().clone(
            snapshot=snapshot,
            permission_policy=permission_policy,
            freeze=freeze,
            share_events=share_events,
        )
        if isinstance(cloned, SpyToolExecutor):
            cloned.ended_invocations = self.ended_invocations
            cloned._calls = self._calls
            cloned._locks = self._locks
        return cloned

    def end_invocation(self, invocation_id: str) -> None:
        """Record invocation termination and perform standard cleanup.

        Args:
            invocation_id: Identifier of the completed invocation.
        """
        self.ended_invocations.append(invocation_id)
        super().end_invocation(invocation_id)


def _setup_runtime(
    monkeypatch: pytest.MonkeyPatch,
    turns: list[FakeTurn] | None = None,
) -> tuple[CodexRuntime, ToolRegistry, SpyToolExecutor]:
    """Configure a CodexRuntime with a SpyToolExecutor and mock SDK.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
        turns: Optional list of scripted FakeTurn instances.

    Returns:
        Tuple of (runtime, registry, spy_executor).
    """
    sdk = FakeSDK(turns=turns)
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread(*args: Any, **kwargs: Any) -> FakeThread:
        """Return a FakeThread linked to the fake SDK."""
        return FakeThread(sdk, thread_id="thread-controlled-turn-1")

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread,
    )

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    registry = ToolRegistry()
    registry.register(_calc_add)
    executor = SpyToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
    )
    return runtime, registry, executor


@pytest.mark.asyncio
async def test_controlled_turn_ainvoke_success_cleans_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify successful controlled_turn invocation cleans ToolExecutor exactly once."""
    turn_id = "turn-success-1"
    turn = FakeTurn(_notifications(status="completed"), turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    # Pre-populate deduplication state to verify complete evacuation
    dummy_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    executor._calls[(turn_id, "call-1")] = dummy_future
    executor._locks[turn_id] = asyncio.Lock()

    model = runtime.model(profile="controlled_turn", level="low").with_tools(
        registry, executor=executor
    )
    result = await model.ainvoke("calculate sum")

    assert result.output == "ok"
    # Exactly one cleanup call occurred
    assert executor.ended_invocations == [turn_id]
    # Deduplication and lock state for this invocation was evacuated
    assert (turn_id, "call-1") not in executor._calls
    assert turn_id not in executor._locks

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_turn_ainvoke_failure_cleans_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failed controlled_turn invocation cleans ToolExecutor exactly once."""
    turn_id = "turn-fail-1"
    turn = FakeTurn(_notifications(status="failed"), turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    # Pre-populate deduplication state
    dummy_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    executor._calls[(turn_id, "call-1")] = dummy_future
    executor._locks[turn_id] = asyncio.Lock()

    model = runtime.model(profile="controlled_turn", level="low").with_tools(
        registry, executor=executor
    )

    with pytest.raises(RuntimeUnavailableError):
        await model.ainvoke("calculate sum")

    # Exactly one cleanup call occurred despite turn failure
    assert executor.ended_invocations == [turn_id]
    assert (turn_id, "call-1") not in executor._calls
    assert turn_id not in executor._locks

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_turn_ainvoke_timeout_cleans_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify timed-out controlled_turn invocation cleans ToolExecutor exactly once."""
    turn_id = "turn-timeout-1"
    turn = FakeTurn(delay_seconds=2.0, turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    # Pre-populate deduplication state
    dummy_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    executor._calls[(turn_id, "call-1")] = dummy_future
    executor._locks[turn_id] = asyncio.Lock()

    model = runtime.model(profile="controlled_turn", level="low").with_tools(
        registry, executor=executor
    )

    with pytest.raises(RuntimeTimeoutError):
        await model.ainvoke("slow turn", config=InvocationConfig(timeout_seconds=0.01))

    # Exactly one cleanup call occurred upon timeout
    assert executor.ended_invocations == [turn_id]
    assert (turn_id, "call-1") not in executor._calls
    assert turn_id not in executor._locks

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_turn_ainvoke_cancellation_cleans_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify cancelled controlled_turn invocation cleans ToolExecutor exactly once."""
    turn_id = "turn-cancel-1"
    turn = FakeTurn(delay_seconds=2.0, turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    # Pre-populate deduplication state
    dummy_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    executor._calls[(turn_id, "call-1")] = dummy_future
    executor._locks[turn_id] = asyncio.Lock()

    model = runtime.model(profile="controlled_turn", level="low").with_tools(
        registry, executor=executor
    )

    async def _invoke() -> None:
        """Run ainvoke in background task."""
        await model.ainvoke("will be cancelled")

    task = asyncio.create_task(_invoke())
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises((asyncio.CancelledError, CancellationError)):
        await task

    # Exactly one cleanup call occurred upon cancellation
    assert executor.ended_invocations == [turn_id]
    assert (turn_id, "call-1") not in executor._calls
    assert turn_id not in executor._locks

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_turn_astream_full_consumption_cleans_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fully consumed stream cleans ToolExecutor exactly once."""
    turn_id = "turn-stream-full-1"
    turn = FakeTurn(_notifications(status="completed"), turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    # Pre-populate deduplication state
    dummy_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    executor._calls[(turn_id, "call-1")] = dummy_future
    executor._locks[turn_id] = asyncio.Lock()

    model = runtime.model(profile="controlled_turn", level="low").with_tools(
        registry, executor=executor
    )

    events: list[RuntimeEvent] = []
    async for event in model.astream("stream input"):
        events.append(event)

    assert len(events) > 0
    # Exactly one cleanup call occurred
    assert executor.ended_invocations == [turn_id]
    assert (turn_id, "call-1") not in executor._calls
    assert turn_id not in executor._locks

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_turn_astream_early_break_cleans_tool_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify early stream break cleans ToolExecutor exactly once."""
    turn_id = "turn-stream-break-1"
    turn = FakeTurn(_notifications(status="completed"), turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    # Pre-populate deduplication state
    dummy_future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    executor._calls[(turn_id, "call-1")] = dummy_future
    executor._locks[turn_id] = asyncio.Lock()

    model = runtime.model(profile="controlled_turn", level="low").with_tools(
        registry, executor=executor
    )

    received: list[RuntimeEvent] = []
    stream = cast(Any, model.astream("stream break input"))
    async for event in stream:
        received.append(event)
        break
    await stream.aclose()

    assert len(received) == 1
    # Exactly one cleanup call occurred despite early stream break
    assert executor.ended_invocations == [turn_id]
    assert (turn_id, "call-1") not in executor._calls
    assert turn_id not in executor._locks

    await runtime.close()


@pytest.mark.asyncio
async def test_controlled_turn_cleanup_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that multiple cleanup invocations on a single turn are idempotent."""
    turn_id = "turn-idempotent-1"
    turn = FakeTurn(_notifications(status="completed"), turn_id=turn_id)
    runtime, registry, executor = _setup_runtime(monkeypatch, turns=[turn])
    await runtime.start()

    model = cast(
        _CodexModel,
        runtime.model(profile="controlled_turn", level="low").with_tools(
            registry, executor=executor
        ),
    )

    run, workspace = await model._start_run("test input", False, InvocationConfig())
    cleanup_fn = run.cleanup
    assert cleanup_fn is not None

    # Call cleanup multiple times
    cleanup_fn()
    cleanup_fn()
    cleanup_fn()

    assert executor.ended_invocations == [turn_id]

    await runtime.close()
