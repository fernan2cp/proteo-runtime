"""Unit tests for task lifecycle, tool binding validation, instructions, and error taxonomy."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from proteo_runtime.core.errors import (
    CapabilityError,
    ConfigurationError,
    ContextPolicyError,
    SessionBusyError,
    SessionNotFoundError,
    ToolDeniedError,
    ToolExecutionError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import InvocationConfig
from proteo_runtime.core.task import RuntimeTask, TaskState
from proteo_runtime.providers.codex.experimental import CodexToolMux
from proteo_runtime.providers.codex.runtime import CodexRuntime, _CodexTask
from proteo_runtime.testing.fakes import FakeRuntime, FakeTask, FakeTurn
from proteo_runtime.tools import (
    ToolExecutor,
    ToolFailurePolicy,
    ToolPermissionPolicy,
    ToolRegistry,
    ToolRequest,
    ToolRetryPolicy,
    runtime_tool,
)

# Ensure tests/unit is available for imports
_unit_dir = str(Path(__file__).resolve().parent.parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import (  # noqa: E402
    FakeNotification,
    FakeSDK,
    FakeThread,
    install_sdk,
)
from test_codex_provider import (  # noqa: E402
    FakeTurn as SDKFakeTurn,
)


@runtime_tool(name="calc_add", description="Add two integers.", permission="calc.add")
async def _calc_add(a: int, b: int) -> int:
    """Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Sum of a and b.
    """
    return a + b


@runtime_tool(name="calc_sub", description="Subtract two integers.", permission="calc.sub")
async def _calc_sub(a: int, b: int) -> int:
    """Subtract b from a.

    Args:
        a: First number.
        b: Second number.

    Returns:
        Difference of a and b.
    """
    return a - b


def _task_state(task: RuntimeTask[Any]) -> TaskState:
    """Return the current lifecycle state of a task without static narrowing.

    Args:
        task: Target runtime task.

    Returns:
        Current lifecycle state of the task.
    """
    state = task.state
    assert isinstance(state, TaskState)
    return state


@pytest.mark.asyncio
async def test_task_tool_binding_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate mandatory tool registry and optional executor validation rules."""
    install_sdk(monkeypatch, FakeSDK())
    empty_registry = ToolRegistry()
    valid_registry = ToolRegistry()
    valid_registry.register(_calc_add)

    mismatched_executor = ToolExecutor(empty_registry)
    matching_executor = ToolExecutor(
        valid_registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
    )

    for runtime in (
        FakeRuntime(),
        CodexRuntime(experimental_dynamic_tools=True),
    ):
        if isinstance(runtime, CodexRuntime):
            await runtime.start()

        # 1. Missing registry fails
        with pytest.raises(CapabilityError, match="A host-tool registry is required"):
            await runtime.task("controlled_agent", registry=None)

        # 2. Empty registry fails
        with pytest.raises(CapabilityError, match="must contain at least one tool"):
            await runtime.task("controlled_agent", registry=empty_registry)

        # 3. Mismatched executor fails
        with pytest.raises(
            CapabilityError, match="Tool executor does not match the registry snapshot"
        ):
            await runtime.task(
                "controlled_agent", registry=valid_registry, executor=mismatched_executor
            )

        # 4. Valid registry with default executor succeeds
        task1 = await runtime.task("controlled_agent", registry=valid_registry)
        assert task1.id.startswith("task_")
        await task1.close()

        # 5. Valid registry with matching executor succeeds
        task2 = await runtime.task(
            "controlled_agent", registry=valid_registry, executor=matching_executor
        )
        assert task2.id.startswith("task_")
        await task2.close()

        if isinstance(runtime, CodexRuntime):
            await runtime.close()


@pytest.mark.asyncio
async def test_task_instructions_persistence_and_immutability() -> None:
    """Verify task instructions are persisted and frozen as a read-only property."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime()

    task = await runtime.task(
        "controlled_agent",
        instructions="You are an authoritative sales quoting assistant.",
        registry=registry,
    )
    assert task.instructions == "You are an authoritative sales quoting assistant."

    with pytest.raises(AttributeError):
        # Read-only property cannot be reassigned
        task.instructions = "new instructions"  # type: ignore[misc]

    await task.close()


@pytest.mark.asyncio
async def test_task_prohibited_config_overrides() -> None:
    """Verify attempts to override frozen model or reasoning_effort fail with ConfigurationError."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime(turns=[FakeTurn(value="Turn response")])

    task = await runtime.task("controlled_agent", registry=registry)

    # 1. Overriding model is prohibited
    with pytest.raises(ConfigurationError, match="Cannot change model"):
        await task.ainvoke("input", config=InvocationConfig(model="gpt-5.6-sol"))

    # 2. Overriding reasoning_effort is prohibited
    with pytest.raises(ConfigurationError, match="Cannot change reasoning effort"):
        await task.ainvoke("input", config=InvocationConfig(reasoning_effort="ultra"))

    # 3. Safe per-turn settings (timeout_seconds, metadata, include_raw) succeed
    result = await task.ainvoke(
        "input",
        config=InvocationConfig(timeout_seconds=30.0, include_raw=True, metadata={"test": "ok"}),
    )
    assert result.value == "Turn response"

    await task.close()


@pytest.mark.asyncio
async def test_task_single_turn_concurrency_lock() -> None:
    """Verify concurrent turns on the same task raise SessionBusyError."""
    registry = ToolRegistry()
    registry.register(_calc_add)

    runtime = FakeRuntime()
    task = await runtime.task("controlled_agent", registry=registry)

    # Acquire the internal lock to simulate an in-flight turn
    await task._lock.acquire()
    try:
        with pytest.raises(SessionBusyError, match="Task already has an active turn"):
            await task.ainvoke("second turn")
    finally:
        task._lock.release()

    await task.close()


@pytest.mark.asyncio
async def test_task_user_only_replay_protection() -> None:
    """Verify task turns reject non-user role messages under ContextPolicy.RUNTIME."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime(turns=[FakeTurn(value="ok"), FakeTurn(value="ok")])

    task = await runtime.task("controlled_agent", registry=registry)

    # 1. Plain string works
    res1 = await task.ainvoke("user prompt")
    assert res1.value == "ok"

    # 2. RuntimeInput with user message works
    res2 = await task.ainvoke(RuntimeInput.from_value("user prompt"))
    assert res2.value == "ok"

    # 3. Assistant message is prohibited
    assistant_input = RuntimeInput(
        messages=(RuntimeMessage("assistant", (TextContent("assistant text"),)),)
    )
    with pytest.raises(
        ContextPolicyError, match="task turns only accept messages with role 'user'"
    ):
        await task.ainvoke(assistant_input)

    # 4. System message is prohibited
    system_input = RuntimeInput(
        messages=(RuntimeMessage("system", (TextContent("system instructions"),)),)
    )
    with pytest.raises(
        ContextPolicyError, match="task turns only accept messages with role 'user'"
    ):
        await task.ainvoke(system_input)

    # 5. Tool message is prohibited
    tool_input = RuntimeInput(messages=(RuntimeMessage("tool", (TextContent("tool response"),)),))
    with pytest.raises(
        ContextPolicyError, match="task turns only accept messages with role 'user'"
    ):
        await task.ainvoke(tool_input)

    await task.close()


@pytest.mark.asyncio
async def test_task_non_resumability_entry_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify resume_session rejects ephemeral task identifiers before SessionCodec."""
    install_sdk(monkeypatch, FakeSDK())
    registry = ToolRegistry()
    registry.register(_calc_add)

    for runtime in (
        FakeRuntime(),
        CodexRuntime(experimental_dynamic_tools=True),
    ):
        if isinstance(runtime, CodexRuntime):
            await runtime.start()

        task = await runtime.task("controlled_agent", registry=registry)
        task_id = task.id
        assert task_id.startswith("task_")

        # 1. Active task cannot be resumed as a session
        with pytest.raises(
            SessionNotFoundError,
            match=f"Task '{task_id}' is ephemeral and cannot be resumed as a session",
        ):
            await runtime.resume_session(task_id)

        # 2. Closed task cannot be resumed as a session
        await task.close()
        with pytest.raises(
            SessionNotFoundError,
            match=f"Task '{task_id}' is ephemeral and cannot be resumed as a session",
        ):
            await runtime.resume_session(task_id)

        # 3. Non-task identifier fails later during normal codec processing
        with pytest.raises(Exception) as exc_info:
            await runtime.resume_session("regular_invalid_descriptor")
        assert "is ephemeral and cannot be resumed" not in str(exc_info.value)

        if isinstance(runtime, CodexRuntime):
            await runtime.close()


@pytest.mark.asyncio
async def test_task_post_close_invalidation_and_idempotency() -> None:
    """Verify task teardown idempotency, registry unregistration, and post-close invalidation."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime()

    task = await runtime.task("controlled_agent", registry=registry)
    task_id = task.id
    assert runtime.get_task(task_id) is task
    assert task.state.value == "open"

    # 1. First close transitions to CLOSED
    await task.close()
    assert task.state.value == "closed"

    # 2. Subsequent close is idempotent
    await task.close()
    await task.close()
    assert task.state.value == "closed"

    # 3. get_task raises SessionNotFoundError
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        runtime.get_task(task_id)

    # 4. ainvoke, astream, and interrupt raise SessionNotFoundError
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.ainvoke("input")

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        async for _ in task.astream("input"):
            pass

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.interrupt()


@pytest.mark.asyncio
async def test_task_tool_event_task_id_propagation() -> None:
    """Verify all tool events emitted during task execution propagate task_id."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
    )

    runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value="Result is 3",
                tool_calls=(("call-1", "calc_add", {"a": 1, "b": 2}),),
            )
        ]
    )

    task = await runtime.task("controlled_agent", registry=registry, executor=executor)
    result = await task.ainvoke("add 1 and 2")
    assert result.value == "Result is 3"
    assert result.task_id == task.id

    tool_events = [
        event
        for event in executor.events
        if event.kind
        in {
            RuntimeEventKind.TOOL_REQUESTED,
            RuntimeEventKind.TOOL_STARTED,
            RuntimeEventKind.TOOL_COMPLETED,
        }
    ]
    assert len(tool_events) >= 3
    for event in tool_events:
        assert event.task_id == task.id
        assert event.session_id is None

    await task.close()


def test_codex_tool_mux_fail_closed_on_unregistered_route() -> None:
    """Verify CodexToolMux fails closed for unregistered routes and non-tool methods."""
    mux = CodexToolMux()
    # 1. Non-tool method is declined
    decline_res = mux("item/approval/request", {})
    assert decline_res == {"decision": "decline", "error": "host-managed tools only"}

    # 2. Unregistered route fails closed with success=False and tool_denied
    denied_res = mux("item/tool/call", {"threadId": "unregistered", "turnId": "turn-1"})
    assert denied_res["success"] is False
    assert "tool_denied" in denied_res["contentItems"][0]["text"]


@pytest.mark.asyncio
async def test_codex_task_close_during_turn_startup_ainvoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify concurrent close() during turn startup aborts cleanly and raises SessionNotFoundError."""
    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread_1(*args: Any, **kwargs: Any) -> FakeThread:
        return FakeThread(sdk, thread_id="thread-task-1")

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread_1,
    )

    registry = ToolRegistry()
    registry.register(_calc_add)

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=registry)
    assert isinstance(task, _CodexTask)
    task_id = task.id
    workspace_dir = task._workspace
    assert workspace_dir.exists()

    turn_started = asyncio.Event()
    turn_release = asyncio.Event()
    fake_turn = SDKFakeTurn()

    async def blocking_turn(*args: Any, **kwargs: Any) -> SDKFakeTurn:
        """Simulate turn startup in-flight waiting for completion.

        Args:
            *args: Positional arguments passed to turn.
            **kwargs: Keyword arguments passed to turn.

        Returns:
            Configured fake SDK turn double.
        """
        turn_started.set()
        await turn_release.wait()
        return fake_turn

    task._thread.turn = blocking_turn

    # 1. Start turn invocation
    turn_task = asyncio.create_task(task.ainvoke("prompt"))
    await turn_started.wait()

    # Turn startup is awaiting turn(); _active_run is not yet registered
    assert _task_state(task) == TaskState.OPEN
    assert task._active_run is None
    assert task._lock.locked()

    # 2. Concurrently initiate task closure
    close_task = asyncio.create_task(task.close())
    await asyncio.sleep(0)

    # Task transitions to CLOSING while waiting for turn startup to abort/exit
    assert _task_state(task) == TaskState.CLOSING
    assert workspace_dir.exists()

    # 3. New external calls fail-fast with SessionNotFoundError during CLOSING
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.ainvoke("concurrent invocation")

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        async for _ in task.astream("concurrent stream"):
            pass

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.interrupt()

    # 4. Release turn startup
    turn_release.set()

    # The in-flight ainvoke detects CLOSING state, interrupts handle, and raises SessionNotFoundError
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await turn_task

    # close() completes cleanly once the lock is released
    await close_task

    # 5. Verify post-close invariants
    assert _task_state(task) == TaskState.CLOSED
    assert not workspace_dir.exists()
    assert fake_turn.interrupted is True
    assert any("thread/delete" in str(call) for call in sdk.delete_calls)
    closed_events = [
        event
        for event in runtime.events
        if event.kind == RuntimeEventKind.TASK_CLOSED and event.task_id == task_id
    ]
    assert len(closed_events) == 1

    await runtime.close()


@pytest.mark.asyncio
async def test_codex_task_close_during_turn_startup_astream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify concurrent close() during stream startup aborts cleanly and raises SessionNotFoundError."""
    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread_2(*args: Any, **kwargs: Any) -> FakeThread:
        return FakeThread(sdk, thread_id="thread-task-2")

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread_2,
    )

    registry = ToolRegistry()
    registry.register(_calc_add)

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=registry)
    assert isinstance(task, _CodexTask)
    task_id = task.id
    workspace_dir = task._workspace
    assert workspace_dir.exists()

    turn_started = asyncio.Event()
    turn_release = asyncio.Event()
    fake_turn = SDKFakeTurn()

    async def blocking_turn(*args: Any, **kwargs: Any) -> SDKFakeTurn:
        """Simulate stream turn startup in-flight waiting for completion.

        Args:
            *args: Positional arguments passed to turn.
            **kwargs: Keyword arguments passed to turn.

        Returns:
            Configured fake SDK turn double.
        """
        turn_started.set()
        await turn_release.wait()
        return fake_turn

    task._thread.turn = blocking_turn

    async def _drain_stream() -> list[RuntimeEvent]:
        """Iterate over task stream events.

        Returns:
            Collected runtime events.
        """
        events: list[RuntimeEvent] = []
        async for event in task.astream("stream prompt"):
            events.append(event)
        return events

    # 1. Start streaming turn
    stream_task = asyncio.create_task(_drain_stream())
    await turn_started.wait()

    assert _task_state(task) == TaskState.OPEN
    assert task._active_run is None
    assert task._lock.locked()

    # 2. Concurrently initiate task closure
    close_task = asyncio.create_task(task.close())
    await asyncio.sleep(0)

    assert _task_state(task) == TaskState.CLOSING
    assert workspace_dir.exists()

    # 3. New external calls fail-fast with SessionNotFoundError during CLOSING
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.ainvoke("concurrent invocation")

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        async for _ in task.astream("concurrent stream"):
            pass

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.interrupt()

    # 4. Release stream turn startup
    turn_release.set()

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await stream_task

    await close_task

    # 5. Verify post-close invariants
    assert _task_state(task) == TaskState.CLOSED
    assert not workspace_dir.exists()
    assert fake_turn.interrupted is True
    assert any("thread/delete" in str(call) for call in sdk.delete_calls)
    closed_events = [
        event
        for event in runtime.events
        if event.kind == RuntimeEventKind.TASK_CLOSED and event.task_id == task_id
    ]
    assert len(closed_events) == 1

    await runtime.close()


@pytest.mark.asyncio
async def test_codex_task_close_during_active_turn_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify close() during active turn cancels via internal primitive and completes teardown (SCEN-024)."""
    stream_active = asyncio.Event()
    stream_release = asyncio.Event()

    class StallingTurn(SDKFakeTurn):
        """SDK fake turn that pauses while streaming notifications."""

        async def stream(self) -> AsyncIterator[FakeNotification]:
            """Stream notifications with a pause.

            Yields:
                Fake notifications for turn lifecycle.
            """
            stream_active.set()
            for notification in self.notifications:
                yield notification
            await stream_release.wait()

    sdk = FakeSDK(turns=[StallingTurn()])
    install_sdk(monkeypatch, sdk)

    async def _fake_start_thread_3(*args: Any, **kwargs: Any) -> FakeThread:
        return FakeThread(sdk, thread_id="thread-task-3")

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.start_thread",
        _fake_start_thread_3,
    )

    registry = ToolRegistry()
    registry.register(_calc_add)

    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=registry)
    assert isinstance(task, _CodexTask)
    task_id = task.id
    workspace_dir = task._workspace
    assert workspace_dir.exists()

    async def _run_turn() -> None:
        """Execute a turn that stalls during streaming."""
        async for _ in task.astream("active prompt"):
            pass

    turn_task = asyncio.create_task(_run_turn())
    await stream_active.wait()

    # Active run is now registered
    assert task._active_run is not None
    assert _task_state(task) == TaskState.OPEN

    # 1. Initiate task.close() while turn is running
    close_task = asyncio.create_task(task.close())
    await asyncio.sleep(0)

    # 2. State transitions to CLOSING; public interrupt() fails with SessionNotFoundError
    assert _task_state(task) == TaskState.CLOSING
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.interrupt()

    # 3. Unblock stream so internal cancellation / cleanup finishes
    stream_release.set()

    # Both turn and close finish cleanly
    with suppress(Exception):
        await turn_task
    await close_task

    # 4. Verify post-close state
    assert _task_state(task) == TaskState.CLOSED
    assert not workspace_dir.exists()
    closed_events = [
        event
        for event in runtime.events
        if event.kind == RuntimeEventKind.TASK_CLOSED and event.task_id == task_id
    ]
    assert len(closed_events) == 1

    await runtime.close()


@pytest.mark.asyncio
async def test_fake_task_close_during_turn_startup() -> None:
    """Verify concurrent close() on FakeTask coordinates with in-flight turn execution."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime()

    task = await runtime.task("controlled_agent", registry=registry)
    assert isinstance(task, FakeTask)
    task_id = task.id

    turn_started = asyncio.Event()
    turn_release = asyncio.Event()
    original_exec = runtime._execute_task_turn

    async def blocking_execute(*args: Any, **kwargs: Any) -> Any:
        """Simulate task turn execution pausing under lock.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Task turn execution tuple.
        """
        turn_started.set()
        await turn_release.wait()
        return await original_exec(*args, **kwargs)

    runtime._execute_task_turn = blocking_execute  # type: ignore[method-assign]

    # 1. Start ainvoke
    turn_task = asyncio.create_task(task.ainvoke("input"))
    await turn_started.wait()

    assert _task_state(task) == TaskState.OPEN
    assert task._lock.locked()

    # 2. Close task concurrently
    close_task = asyncio.create_task(task.close())
    await asyncio.sleep(0)

    assert _task_state(task) == TaskState.CLOSING

    # 3. Fail-fast during CLOSING
    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.ainvoke("input")

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        async for _ in task.astream("input"):
            pass

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await task.interrupt()

    # 4. Release turn
    turn_release.set()

    with pytest.raises(SessionNotFoundError, match=f"Task '{task_id}' not found or already closed"):
        await turn_task

    await close_task

    assert _task_state(task) == TaskState.CLOSED
    assert task_id not in runtime._tasks
    closed_events = [
        event
        for event in runtime.events
        if event.kind == RuntimeEventKind.TASK_CLOSED and event.task_id == task_id
    ]
    assert len(closed_events) == 1


@pytest.mark.asyncio
async def test_task_concurrent_close_emits_task_closed_once() -> None:
    """Verify concurrent close() calls are idempotent and emit TASK_CLOSED exactly once."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime()

    task = await runtime.task("controlled_agent", registry=registry)
    task_id = task.id

    # Gather 5 concurrent close() calls
    await asyncio.gather(
        task.close(),
        task.close(),
        task.close(),
        task.close(),
        task.close(),
    )

    assert task.state is TaskState.CLOSED
    closed_events = [
        event
        for event in runtime.events
        if event.kind == RuntimeEventKind.TASK_CLOSED and event.task_id == task_id
    ]
    assert len(closed_events) == 1


@pytest.mark.asyncio
async def test_runtime_close_cascades_to_open_tasks() -> None:
    """Verify closing the runtime cascades teardown to all active in-memory tasks."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime()

    task1 = await runtime.task("controlled_agent", registry=registry)
    task2 = await runtime.task("controlled_agent", registry=registry)

    assert task1.id in runtime._tasks
    assert task2.id in runtime._tasks
    assert task1.state.value == "open"
    assert task2.state.value == "open"

    await runtime.close()

    assert task1.state.value == "closed"
    assert task2.state.value == "closed"
    assert len(runtime._tasks) == 0


# --- Gap 3 Shutdown Tests ---


@pytest.mark.asyncio
async def test_codex_runtime_shutdown_task_thread_deleted_before_sdk_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify provider thread deletion strictly precedes SDK transport closure."""
    fake_sdk = FakeSDK()
    install_sdk(monkeypatch, fake_sdk)

    operation_log: list[str] = []
    orig_request = fake_sdk.request

    async def tracking_request(*args: Any, **kwargs: Any) -> None:
        """Record thread deletion and ensure SDK client transport is active."""
        if fake_sdk.close_count > 0:
            raise RuntimeError("Cannot delete thread after SDK is closed!")
        method = args[0] if args else ""
        operation_log.append(f"request:{method}")
        await orig_request(*args, **kwargs)

    fake_sdk._client.request = tracking_request

    orig_close = fake_sdk.close

    async def tracking_close() -> None:
        """Record SDK closure."""
        operation_log.append("sdk_close")
        await orig_close()

    fake_sdk.close = tracking_close  # type: ignore[method-assign]

    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=registry)
    task_id = task.id
    assert _task_state(task) is TaskState.OPEN

    await runtime.close()

    assert "request:thread/delete" in operation_log
    assert "sdk_close" in operation_log
    delete_idx = operation_log.index("request:thread/delete")
    close_idx = operation_log.index("sdk_close")
    assert delete_idx < close_idx, "Thread deletion must occur before SDK is closed"

    assert _task_state(task) is TaskState.CLOSED
    task_closed_events = [
        e for e in runtime.events if e.kind is RuntimeEventKind.TASK_CLOSED and e.task_id == task_id
    ]
    runtime_stopped_events = [
        e for e in runtime.events if e.kind is RuntimeEventKind.RUNTIME_STOPPED
    ]
    assert len(task_closed_events) == 1
    assert len(runtime_stopped_events) == 1
    assert runtime.events.index(task_closed_events[0]) < runtime.events.index(
        runtime_stopped_events[0]
    )


@pytest.mark.asyncio
async def test_codex_runtime_shutdown_multiple_tasks_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify multiple active tasks have their provider threads deleted before SDK close."""
    fake_sdk = FakeSDK()
    install_sdk(monkeypatch, fake_sdk)

    operation_log: list[str] = []
    orig_request = fake_sdk.request

    async def tracking_request(*args: Any, **kwargs: Any) -> None:
        """Record thread deletion calls."""
        if fake_sdk.close_count > 0:
            raise RuntimeError("SDK is closed!")
        operation_log.append(f"request:{args[0] if args else ''}")
        await orig_request(*args, **kwargs)

    fake_sdk._client.request = tracking_request

    orig_close = fake_sdk.close

    async def tracking_close() -> None:
        """Record SDK closure."""
        operation_log.append("sdk_close")
        await orig_close()

    fake_sdk.close = tracking_close  # type: ignore[method-assign]

    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    tasks = [
        await runtime.task("controlled_agent", registry=registry),
        await runtime.task("controlled_agent", registry=registry),
        await runtime.task("controlled_agent", registry=registry),
    ]
    for t in tasks:
        assert _task_state(t) is TaskState.OPEN

    await runtime.close()

    delete_indices = [i for i, op in enumerate(operation_log) if op == "request:thread/delete"]
    assert len(delete_indices) == 3, "All 3 tasks must delete their threads"
    close_idx = operation_log.index("sdk_close")
    assert all(idx < close_idx for idx in delete_indices), (
        "All thread deletions must precede SDK close"
    )

    for t in tasks:
        assert _task_state(t) is TaskState.CLOSED
        with pytest.raises(SessionNotFoundError):
            runtime.get_task(t.id)
    assert len(runtime._tasks) == 0


@pytest.mark.asyncio
async def test_codex_runtime_shutdown_resilience_to_task_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that a failure in one task's cleanup does not block other tasks or SDK closure."""
    fake_sdk = FakeSDK()
    install_sdk(monkeypatch, fake_sdk)

    call_count = 0
    orig_request = fake_sdk.request

    async def failing_request(*args: Any, **kwargs: Any) -> None:
        """Simulate a failure on the first task's thread deletion."""
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated remote failure during thread deletion")
        await orig_request(*args, **kwargs)

    fake_sdk._client.request = failing_request

    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task1 = await runtime.task("controlled_agent", registry=registry)
    task2 = await runtime.task("controlled_agent", registry=registry)

    await runtime.close()

    # SDK must be closed despite task1's failure
    assert fake_sdk.close_count == 1
    assert runtime._closed is True
    assert runtime._sdk is None
    assert _task_state(task1) is TaskState.CLOSED
    assert _task_state(task2) is TaskState.CLOSED

    closed_events = [e for e in runtime.events if e.kind is RuntimeEventKind.TASK_CLOSED]
    assert len(closed_events) == 2, "Both tasks must emit TASK_CLOSED exactly once"
    stopped_events = [e for e in runtime.events if e.kind is RuntimeEventKind.RUNTIME_STOPPED]
    assert len(stopped_events) == 1, "RUNTIME_STOPPED must be emitted"


@pytest.mark.asyncio
async def test_codex_runtime_shutdown_idempotency_and_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify concurrent and repeated close() calls execute cleanly and idempotently."""
    fake_sdk = FakeSDK()
    install_sdk(monkeypatch, fake_sdk)

    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=registry)

    # Concurrently close runtime
    await asyncio.gather(
        runtime.close(),
        runtime.close(),
        runtime.close(),
    )

    assert fake_sdk.close_count == 1
    assert _task_state(task) is TaskState.CLOSED
    stopped_events = [e for e in runtime.events if e.kind is RuntimeEventKind.RUNTIME_STOPPED]
    assert len(stopped_events) == 1

    # Sequential subsequent close call returns immediately without side-effects
    await runtime.close()
    assert fake_sdk.close_count == 1


# --- Gap 4 Frozen Tool Authority Tests ---


@pytest.mark.asyncio
async def test_task_tool_registry_mutation_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify mutating the tool registry after task creation does not expose new tools."""
    install_sdk(monkeypatch, FakeSDK())

    for runtime in (
        FakeRuntime(),
        CodexRuntime(experimental_dynamic_tools=True),
    ):
        if isinstance(runtime, CodexRuntime):
            await runtime.start()

        registry = ToolRegistry()
        registry.register(_calc_add)

        # 1. Default failure policy (RETURN_ERROR) returns error result
        task = await runtime.task("controlled_agent", registry=registry)

        # Mutate external registry
        registry.register(_calc_sub)
        assert registry.get("calc_sub") is not None

        # Verify task definitions remain frozen with only calc_add
        task_snapshot = getattr(task, "_tool_snapshot", None)
        assert task_snapshot is not None
        assert task_snapshot.get("calc_sub") is None
        assert [d.name for d in task_snapshot.definitions()] == ["calc_add"]

        task_executor = getattr(task, "_tool_executor", None)
        assert task_executor is not None
        assert task_executor.snapshot.get("calc_sub") is None
        assert [d.name for d in task_executor.snapshot.definitions()] == ["calc_add"]

        result = await task_executor.execute(
            ToolRequest(
                invocation_id="inv-test-1",
                call_id="call-test-1",
                name="calc_sub",
                arguments={"a": 10, "b": 3},
                task_id=task.id,
            )
        )
        assert result.success is False
        assert result.error_code == "tool_execution_error"

        # 2. When failure_policy=RAISE, unknown tool raises ToolExecutionError
        executor_raise = ToolExecutor(registry.snapshot(), failure_policy=ToolFailurePolicy.RAISE)
        task_raise = await runtime.task(
            "controlled_agent", registry=registry, executor=executor_raise
        )
        task_raise_executor = getattr(task_raise, "_tool_executor", None)
        assert task_raise_executor is not None

        # Add a 3rd tool to registry
        @runtime_tool(name="calc_mul", description="Multiply", permission="calc.mul")
        async def _calc_mul(a: int, b: int) -> int:
            """Multiply a and b.

            Args:
                a: First number.
                b: Second number.

            Returns:
                Product of a and b.
            """
            return a * b

        registry.register(_calc_mul)
        assert task_raise_executor.snapshot.get("calc_mul") is None

        with pytest.raises(ToolExecutionError) as exc_info:
            await task_raise_executor.execute(
                ToolRequest(
                    invocation_id="inv-test-2",
                    call_id="call-test-2",
                    name="calc_mul",
                    arguments={"a": 2, "b": 3},
                    task_id=task_raise.id,
                )
            )
        assert exc_info.value.code == "tool_execution_error"

        await runtime.close()


@pytest.mark.asyncio
async def test_task_tool_executor_permission_policy_mutation_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify mutating the permission policy on the external executor does not expand task permissions."""
    install_sdk(monkeypatch, FakeSDK())

    for runtime in (
        FakeRuntime(),
        CodexRuntime(experimental_dynamic_tools=True),
    ):
        if isinstance(runtime, CodexRuntime):
            await runtime.start()

        registry = ToolRegistry()
        registry.register(_calc_add)
        registry.register(_calc_sub)

        # Initial executor permits ONLY calc.add, with failure_policy=RAISE
        executor = ToolExecutor(
            registry,
            permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
            failure_policy=ToolFailurePolicy.RAISE,
        )

        task = await runtime.task("controlled_agent", registry=registry, executor=executor)

        # Attempt to expand authority on the external executor
        executor.permission_policy = ToolPermissionPolicy(frozenset({"calc.add", "calc.sub"}))
        assert executor.permission_policy.allows("calc.sub") is True

        # Task executor must retain frozen permission policy (only calc.add allowed)
        task_executor = getattr(task, "_tool_executor", None)
        assert task_executor is not None
        assert task_executor.permission_policy.allows("calc.add") is True
        assert task_executor.permission_policy.allows("calc.sub") is False

        # Direct execution of calc_sub through task executor fails with ToolDeniedError
        with pytest.raises(ToolDeniedError) as exc_info:
            await task_executor.execute(
                ToolRequest(
                    invocation_id="inv-test",
                    call_id="call-test",
                    name="calc_sub",
                    arguments={"a": 10, "b": 3},
                    task_id=task.id,
                )
            )
        assert exc_info.value.code == "tool_denied"

        # Direct attribute reassignment on task executor must be blocked by freeze guard
        with pytest.raises(
            AttributeError, match="Cannot mutate authority attribute 'permission_policy'"
        ):
            task_executor.permission_policy = ToolPermissionPolicy(
                frozenset({"calc.add", "calc.sub"})
            )

        await runtime.close()


@pytest.mark.asyncio
async def test_task_tool_executor_all_authority_attributes_frozen() -> None:
    """Verify that all authority attributes on the bound ToolExecutor are frozen and isolated."""
    registry = ToolRegistry()
    registry.register(_calc_add)

    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
        retry_policy=ToolRetryPolicy(max_attempts=2),
        failure_policy=ToolFailurePolicy.RAISE,
        timeout_seconds=12.0,
        approval_timeout_seconds=25.0,
    )

    runtime = FakeRuntime()
    task = await runtime.task("controlled_agent", registry=registry, executor=executor)
    task_executor = getattr(task, "_tool_executor", None)
    assert task_executor is not None
    assert task_executor.is_frozen is True

    # Mutate external executor
    executor.timeout_seconds = 99.0
    executor.retry_policy = ToolRetryPolicy(max_attempts=3)
    executor.failure_policy = ToolFailurePolicy.RETURN_ERROR
    executor.approval_timeout_seconds = 88.0

    # Verify task executor retains frozen values
    assert task_executor.timeout_seconds == 12.0
    assert task_executor.retry_policy.max_attempts == 2
    assert task_executor.failure_policy is ToolFailurePolicy.RAISE
    assert task_executor.approval_timeout_seconds == 25.0

    # Verify all authority attributes reject mutation
    with pytest.raises(AttributeError, match="Cannot mutate authority attribute 'timeout_seconds'"):
        task_executor.timeout_seconds = 50.0
    with pytest.raises(AttributeError, match="Cannot mutate authority attribute 'retry_policy'"):
        task_executor.retry_policy = ToolRetryPolicy(max_attempts=1)
    with pytest.raises(AttributeError, match="Cannot mutate authority attribute 'failure_policy'"):
        task_executor.failure_policy = ToolFailurePolicy.RETURN_ERROR
    with pytest.raises(
        AttributeError, match="Cannot mutate authority attribute 'approval_timeout_seconds'"
    ):
        task_executor.approval_timeout_seconds = 10.0
    with pytest.raises(
        AttributeError, match="Cannot mutate authority attribute 'approval_handler'"
    ):
        task_executor.approval_handler = None
    with pytest.raises(AttributeError, match="Cannot mutate authority attribute 'snapshot'"):
        task_executor.snapshot = ToolRegistry().snapshot()

    await runtime.close()


@pytest.mark.asyncio
async def test_task_frozen_authority_multi_turn_ac_cal_015() -> None:
    """Demonstrate AC-CAL-015: authority(task, turn N) <= authority(task, creation) across turns."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    registry.register(_calc_sub)

    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"calc.add"})),
        failure_policy=ToolFailurePolicy.RAISE,
    )

    # Scripted turns: turn 1 calls calc_add (allowed); turn 2 attempts calc_sub (denied)
    runtime = FakeRuntime(
        turns=[
            FakeTurn(
                value="turn 1 ok",
                tool_calls=(("call-1", "calc_add", {"a": 2, "b": 3}),),
            ),
            FakeTurn(
                value="turn 2 attempt",
                tool_calls=(("call-2", "calc_sub", {"a": 10, "b": 4}),),
            ),
        ]
    )

    task = await runtime.task("controlled_agent", registry=registry, executor=executor)

    # Turn 1: calc_add succeeds
    result1 = await task.ainvoke("run turn 1")
    assert result1.value == "turn 1 ok"

    # External actor attempts to broaden authority before Turn 2
    executor.permission_policy = ToolPermissionPolicy(frozenset({"calc.add", "calc.sub"}))

    @runtime_tool(name="dangerous_tool", description="Dangerous operation", permission="danger")
    async def _danger() -> str:
        """Dangerous helper.

        Returns:
            Status string.
        """
        return "danger"

    registry.register(_danger)

    # Turn 2: Attempting calc_sub is still DENIED because task authority is frozen
    with pytest.raises(ToolDeniedError):
        await task.ainvoke("run turn 2")

    # Verify task does not know dangerous_tool
    task_snapshot = getattr(task, "_tool_snapshot", None)
    assert task_snapshot is not None
    assert task_snapshot.get("dangerous_tool") is None

    await runtime.close()
