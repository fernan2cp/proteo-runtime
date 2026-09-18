"""Unit tests for resilient task teardown diagnostics and safe failure handling."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from proteo_runtime.core.diagnostics import DiagnosticSeverity
from proteo_runtime.core.errors import CancellationError, RuntimeTimeoutError
from proteo_runtime.core.events import RuntimeEventKind
from proteo_runtime.core.model import InvocationConfig
from proteo_runtime.core.task import TaskState
from proteo_runtime.providers.codex.runtime import CodexRuntime, _CodexTask
from proteo_runtime.testing.fakes import FakeRuntime, FakeTask
from proteo_runtime.tools import ToolRegistry, runtime_tool

_unit_dir = str(Path(__file__).resolve().parent.parent)
if _unit_dir not in sys.path:
    sys.path.insert(0, _unit_dir)

from test_codex_provider import FakeSDK, install_sdk  # noqa: E402

CANARY_SECRET = "sk-live-canary-secret-token-abcdef123456"


@runtime_tool(name="echo_tool", description="Echo input text.", permission="echo.run")
async def _echo_tool(text: str) -> str:
    """Echo text.

    Args:
        text: Input string.

    Returns:
        The exact input string.
    """
    return text


def _create_registry() -> ToolRegistry:
    """Create a registry populated with the echo tool.

    Returns:
        Populated ToolRegistry instance.
    """
    registry = ToolRegistry()
    registry.register(_echo_tool)
    return registry


def _assert_no_canary_leak(task: Any, runtime: Any) -> None:
    """Verify that the canary secret never appears in diagnostics, details, or events.

    Args:
        task: Target task handle.
        runtime: Target runtime instance.
    """
    for diagnostic in task.diagnostics:
        assert CANARY_SECRET not in diagnostic.code
        assert CANARY_SECRET not in diagnostic.message
        assert CANARY_SECRET not in str(diagnostic.details)
    for event in runtime.events:
        assert CANARY_SECRET not in str(event.metadata)
        assert CANARY_SECRET not in str(event.payload)


@pytest.mark.asyncio
async def test_teardown_interrupt_failure_emits_diagnostic_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that an active turn interrupt failure emits a sanitized diagnostic and teardown completes."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    class FakeActiveRun:
        """Stub representing an active turn run whose interrupt fails."""

        async def interrupt(self) -> None:
            """Raise with canary secret."""
            raise RuntimeError(f"Interrupt failed with credential {CANARY_SECRET}")

        async def wait_finished(self) -> None:
            """No-op wait."""

        cleanup: Any = None

    task._active_run = FakeActiveRun()  # type: ignore[assignment]

    await task.close()

    assert task.state == TaskState.CLOSED
    assert task.id not in runtime._tasks

    diagnostics = task.diagnostics
    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.code == "task.cleanup.interrupt_failed"
    assert diag.message == "Failed to interrupt active turn during task teardown"
    assert diag.severity == DiagnosticSeverity.WARNING
    assert diag.details["exception_type"] == "RuntimeError"
    assert diag.details["task_id"] == task.id

    _assert_no_canary_leak(task, runtime)

    closed_events = [e for e in runtime.events if e.kind == RuntimeEventKind.TASK_CLOSED]
    assert len(closed_events) == 1
    event_diags = closed_events[0].metadata.get("diagnostics", [])
    assert len(event_diags) == 1
    assert event_diags[0]["code"] == "task.cleanup.interrupt_failed"

    # Subsequent close is idempotent and does not emit duplicate diagnostics or events
    await task.close()
    assert len(task.diagnostics) == 1
    assert len([e for e in runtime.events if e.kind == RuntimeEventKind.TASK_CLOSED]) == 1

    await runtime.close()


@pytest.mark.asyncio
async def test_teardown_tool_cleanup_failure_emits_diagnostic_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that a tool cleanup failure emits a sanitized diagnostic and deletes context/workspace."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    def failing_cleanup() -> None:
        """Fail with canary secret."""
        raise ValueError(f"Tool state cleanup failed: secret={CANARY_SECRET}")

    class FakeTurnWithFailingCleanup:
        """Turn double with failing cleanup callback."""

        async def interrupt(self) -> None:
            """Clean interrupt."""

        async def wait_finished(self) -> None:
            """Clean wait."""

        cleanup = staticmethod(failing_cleanup)

    task._active_run = FakeTurnWithFailingCleanup()  # type: ignore[assignment]

    thread_deleted = False
    original_delete_thread = sys.modules["proteo_runtime.providers.codex.runtime"].delete_thread

    async def tracking_delete_thread(sdk: Any, thread_id: str) -> None:
        """Track deletion and delegate."""
        nonlocal thread_deleted
        thread_deleted = True
        await original_delete_thread(sdk, thread_id)

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.delete_thread",
        tracking_delete_thread,
    )

    await task.close()

    assert task.state == TaskState.CLOSED
    assert task.id not in runtime._tasks
    assert thread_deleted is True

    diagnostics = task.diagnostics
    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.code == "task.cleanup.tool_state_failed"
    assert diag.message == "Failed to clean up tool state during task teardown"
    assert diag.severity == DiagnosticSeverity.WARNING
    assert diag.details["exception_type"] == "ValueError"

    _assert_no_canary_leak(task, runtime)
    await runtime.close()


@pytest.mark.asyncio
async def test_teardown_provider_delete_failure_emits_diagnostic_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that provider context deletion failure emits diagnostic and still removes workspace."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    async def failing_delete_thread(sdk: Any, thread_id: str) -> None:
        """Fail provider thread deletion."""
        raise ConnectionError(f"Provider thread deletion dropped: {CANARY_SECRET}")

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.delete_thread",
        failing_delete_thread,
    )

    workspace_removed = False
    original_remove_workspace = sys.modules[
        "proteo_runtime.providers.codex.runtime"
    ].remove_workspace

    def tracking_remove_workspace(path: Path) -> None:
        """Track workspace removal."""
        nonlocal workspace_removed
        workspace_removed = True
        original_remove_workspace(path)

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.remove_workspace",
        tracking_remove_workspace,
    )

    await task.close()

    assert task.state == TaskState.CLOSED
    assert task.id not in runtime._tasks
    assert workspace_removed is True

    diagnostics = task.diagnostics
    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.code == "task.cleanup.provider_delete_failed"
    assert diag.message == "Failed to delete provider context during task teardown"
    assert diag.severity == DiagnosticSeverity.WARNING
    assert diag.details["exception_type"] == "ConnectionError"

    _assert_no_canary_leak(task, runtime)
    await runtime.close()


@pytest.mark.asyncio
async def test_teardown_workspace_removal_failure_emits_diagnostic_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that workspace removal failure emits diagnostic and handle finishes closed."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    def failing_remove_workspace(path: Path) -> None:
        """Fail workspace removal with canary."""
        raise OSError(f"Permission denied while wiping {path}: auth={CANARY_SECRET}")

    monkeypatch.setattr(
        "proteo_runtime.providers.codex.runtime.remove_workspace",
        failing_remove_workspace,
    )

    await task.close()

    assert task.state == TaskState.CLOSED
    assert task.id not in runtime._tasks

    diagnostics = task.diagnostics
    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag.code == "task.cleanup.workspace_failed"
    assert diag.message == "Failed to remove task workspace directory during task teardown"
    assert diag.severity == DiagnosticSeverity.WARNING
    assert diag.details["exception_type"] == "OSError"

    _assert_no_canary_leak(task, runtime)
    await runtime.close()


@pytest.mark.asyncio
async def test_teardown_multiple_simultaneous_failures_record_all_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that all teardown failures are captured in sequence without aborting subsequent cleanup."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    class MultiFailTurn:
        """Turn double failing interrupt and cleanup."""

        async def interrupt(self) -> None:
            """Fail interrupt."""
            raise RuntimeError(f"Interrupt error {CANARY_SECRET}")

        async def wait_finished(self) -> None:
            """Wait."""

        def cleanup(self) -> None:
            """Fail cleanup."""
            raise KeyError(f"Cleanup key missing {CANARY_SECRET}")

    task._active_run = MultiFailTurn()  # type: ignore[assignment]

    async def failing_delete(sdk: Any, thread_id: str) -> None:
        """Fail delete_thread."""
        raise TimeoutError(f"Delete thread timed out {CANARY_SECRET}")

    def failing_remove(path: Path) -> None:
        """Fail remove_workspace."""
        raise PermissionError(f"Wipe forbidden {CANARY_SECRET}")

    monkeypatch.setattr("proteo_runtime.providers.codex.runtime.delete_thread", failing_delete)
    monkeypatch.setattr("proteo_runtime.providers.codex.runtime.remove_workspace", failing_remove)

    # Should not raise
    await task.close()

    assert task.state == TaskState.CLOSED
    assert task.id not in runtime._tasks

    diagnostics = task.diagnostics
    assert len(diagnostics) == 4
    assert [d.code for d in diagnostics] == [
        "task.cleanup.interrupt_failed",
        "task.cleanup.tool_state_failed",
        "task.cleanup.provider_delete_failed",
        "task.cleanup.workspace_failed",
    ]

    _assert_no_canary_leak(task, runtime)

    closed_events = [e for e in runtime.events if e.kind == RuntimeEventKind.TASK_CLOSED]
    assert len(closed_events) == 1
    event_diags = closed_events[0].metadata.get("diagnostics", [])
    assert len(event_diags) == 4

    # Runtime also recorded the diagnostics
    assert len(runtime.diagnostics) == 4

    await runtime.close()


@pytest.mark.asyncio
async def test_teardown_tool_executor_fallback_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify tool state failure diagnostic when active_run has no cleanup but tool_executor fails."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    task._active_run = None
    task._active_invocation_id = "turn-inv-999"

    assert task._tool_executor is not None

    def failing_end_invocation(inv_id: str) -> None:
        """Fail end_invocation."""
        raise RuntimeError(f"end_invocation lock error {CANARY_SECRET}")

    monkeypatch.setattr(task._tool_executor, "end_invocation", failing_end_invocation)

    await task.close()

    assert task.state == TaskState.CLOSED
    diagnostics = task.diagnostics
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "task.cleanup.tool_state_failed"
    _assert_no_canary_leak(task, runtime)

    await runtime.close()


@pytest.mark.asyncio
async def test_fake_task_cleanup_failure_records_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify FakeTask records diagnostic when tool executor end_invocation fails."""
    runtime = FakeRuntime()
    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, FakeTask)

    task._active_invocation_id = "fake-inv-1"
    assert task._tool_executor is not None

    def failing_end_invocation(inv_id: str) -> None:
        """Fail fake tool end_invocation."""
        raise RuntimeError(f"Fake executor end error {CANARY_SECRET}")

    monkeypatch.setattr(task._tool_executor, "end_invocation", failing_end_invocation)

    await task.close()

    assert task.state == TaskState.CLOSED
    assert task.id not in runtime._tasks
    diagnostics = task.diagnostics
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "task.cleanup.tool_state_failed"
    assert diagnostics[0].details["exception_type"] == "RuntimeError"

    _assert_no_canary_leak(task, runtime)

    closed_events = [e for e in runtime.events if e.kind == RuntimeEventKind.TASK_CLOSED]
    assert len(closed_events) == 1
    assert len(closed_events[0].metadata.get("diagnostics", [])) == 1

    await runtime.close()


@pytest.mark.asyncio
async def test_task_async_context_manager_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify task handle async context manager enters and closes cleanly on exit."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task_obj = await runtime.task("controlled_agent", registry=_create_registry())
    async with task_obj as task:
        assert task.state == TaskState.OPEN
        assert task.id in runtime._tasks

    assert task_obj.state == TaskState.CLOSED
    assert task_obj.id not in runtime._tasks

    # Verify context manager closes even when body raises
    task2_obj = await runtime.task("controlled_agent", registry=_create_registry())
    with pytest.raises(ValueError, match="test error"):
        async with task2_obj:
            raise ValueError("test error")

    assert task2_obj.state == TaskState.CLOSED
    assert task2_obj.id not in runtime._tasks

    await runtime.close()


@pytest.mark.asyncio
async def test_runtime_close_with_failing_tasks_records_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify CodexRuntime.close() succeeds and captures diagnostics when child tasks fail cleanup."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task1 = await runtime.task("controlled_agent", registry=_create_registry())
    task2 = await runtime.task("controlled_agent", registry=_create_registry())

    def failing_remove(path: Path) -> None:
        """Fail workspace wipe."""
        raise OSError(f"Disk busy: {CANARY_SECRET}")

    monkeypatch.setattr("proteo_runtime.providers.codex.runtime.remove_workspace", failing_remove)

    # Closing runtime triggers close on all active tasks
    await runtime.close()

    assert task1.state == TaskState.CLOSED
    assert task2.state == TaskState.CLOSED
    assert len(task1.diagnostics) == 1
    assert len(task2.diagnostics) == 1
    assert len(runtime.diagnostics) == 2

    _assert_no_canary_leak(task1, runtime)
    _assert_no_canary_leak(task2, runtime)


@pytest.mark.asyncio
async def test_codex_task_interrupt_active_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify task.interrupt() interrupts an active turn and handles failure gracefully."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    interrupted = False

    class ActiveRunDouble:
        async def interrupt(self) -> None:
            nonlocal interrupted
            interrupted = True

        async def wait_finished(self) -> None:
            pass

    task._active_run = ActiveRunDouble()  # type: ignore[assignment]
    await task.interrupt()
    assert interrupted is True

    # Test when interrupt fails inside _interrupt_active_run, it suppresses exception
    class FailingInterruptRun:
        async def interrupt(self) -> None:
            raise RuntimeError("interrupt dropped")

        async def wait_finished(self) -> None:
            pass

    task._active_run = FailingInterruptRun()  # type: ignore[assignment]
    await task.interrupt()

    task._active_run = None
    await task.close()
    await runtime.close()


@pytest.mark.asyncio
async def test_codex_task_close_during_closing_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a second concurrent close awaits _close_event when task is in CLOSING state."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    task._state = TaskState.CLOSING

    async def complete_teardown() -> None:
        await asyncio.sleep(0.02)
        task._state = TaskState.CLOSED
        task._close_event.set()

    asyncio.create_task(complete_teardown())
    await task.close()
    assert task.state == TaskState.CLOSED

    await runtime.close()


@pytest.mark.asyncio
async def test_codex_task_ainvoke_timeout_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify task ainvoke timeout and cancellation error handling and active run interrupt."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    class HangingTurn:
        invocation_id: str = "test-inv-ainvoke"

        async def events(self) -> Any:
            await asyncio.sleep(5.0)
            yield None

        async def interrupt(self) -> None:
            pass

        async def wait_finished(self) -> None:
            pass

        cleanup: Any = None
        result: Any = None

    async def fake_start_turn(prompt: str, effective: Any) -> Any:
        run = HangingTurn()
        task._active_run = run  # type: ignore[assignment]
        return run

    monkeypatch.setattr(task, "_start_turn", fake_start_turn)

    with pytest.raises(RuntimeTimeoutError, match="Codex task turn timed out"):
        await task.ainvoke("prompt", config=InvocationConfig(timeout_seconds=0.01))

    with pytest.raises(CancellationError, match="Codex task turn was cancelled"):
        task_coro = task.ainvoke("prompt")
        asyncio_task = asyncio.create_task(task_coro)
        await asyncio.sleep(0.01)
        asyncio_task.cancel()
        await asyncio_task

    await task.close()
    await runtime.close()


@pytest.mark.asyncio
async def test_codex_task_astream_timeout_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify task astream timeout and cancellation error handling and active run interrupt."""
    install_sdk(monkeypatch, FakeSDK())
    runtime = CodexRuntime(experimental_dynamic_tools=True)
    await runtime.start()

    task = await runtime.task("controlled_agent", registry=_create_registry())
    assert isinstance(task, _CodexTask)

    class HangingStreamTurn:
        invocation_id: str = "test-inv-astream"

        async def events(self) -> Any:
            await asyncio.sleep(5.0)
            yield None

        async def interrupt(self) -> None:
            pass

        async def wait_finished(self) -> None:
            pass

        cleanup: Any = None
        terminal_status: Any = None

    async def fake_start_turn(prompt: str, effective: Any) -> Any:
        run = HangingStreamTurn()
        task._active_run = run  # type: ignore[assignment]
        return run

    monkeypatch.setattr(task, "_start_turn", fake_start_turn)

    with pytest.raises(RuntimeTimeoutError, match="Codex task stream timed out"):
        async for _ in task.astream("prompt", config=InvocationConfig(timeout_seconds=0.01)):
            pass

    with pytest.raises(CancellationError, match="Codex task stream was cancelled"):

        async def consume() -> None:
            async for _ in task.astream("prompt"):
                pass

        asyncio_task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        asyncio_task.cancel()
        await asyncio_task

    await task.close()
    await runtime.close()
