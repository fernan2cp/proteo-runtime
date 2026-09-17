"""Unit tests for task lifecycle, tool binding validation, instructions, and error taxonomy."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from proteo_runtime.core.errors import (
    CapabilityError,
    ConfigurationError,
    ContextPolicyError,
    SessionBusyError,
    SessionNotFoundError,
)
from proteo_runtime.core.events import RuntimeEventKind
from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import InvocationConfig
from proteo_runtime.core.task import TaskState
from proteo_runtime.providers.codex.experimental import CodexToolMux
from proteo_runtime.providers.codex.runtime import CodexRuntime
from proteo_runtime.testing.fakes import FakeRuntime, FakeTurn
from proteo_runtime.tools import (
    ToolExecutor,
    ToolPermissionPolicy,
    ToolRegistry,
    runtime_tool,
)

# Ensure tests/unit is available for imports
_unit_dir = str(Path(__file__).resolve().parent.parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import FakeSDK, install_sdk  # noqa: E402


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
async def test_task_race_prevention_during_closing() -> None:
    """Verify calling ainvoke/astream/interrupt during CLOSING state immediately raises SessionNotFoundError."""
    registry = ToolRegistry()
    registry.register(_calc_add)
    runtime = FakeRuntime()

    task = await runtime.task("controlled_agent", registry=registry)
    task._state = TaskState.CLOSING

    with pytest.raises(SessionNotFoundError, match=f"Task '{task.id}' not found or already closed"):
        await task.ainvoke("input")

    with pytest.raises(SessionNotFoundError, match=f"Task '{task.id}' not found or already closed"):
        async for _ in task.astream("input"):
            pass

    with pytest.raises(SessionNotFoundError, match=f"Task '{task.id}' not found or already closed"):
        await task.interrupt()

    # Reset state to clean up properly
    task._state = TaskState.OPEN
    await task.close()


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
