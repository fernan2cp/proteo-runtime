"""Protocol contract for task-scoped ephemeral controlled agents."""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from .diagnostics import RuntimeDiagnostic
from .errors import ContextPolicyError
from .events import RuntimeEvent
from .input import RuntimeInput
from .model import InvocationConfig, RuntimeResult

T = TypeVar("T")


class TaskState(StrEnum):
    """Lifecycle state machine for task-scoped ephemeral controlled agents."""

    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


def validate_task_input(input: str | RuntimeInput) -> RuntimeInput:
    """Enforce user-only input under ContextPolicy.RUNTIME.

    The neutral RuntimeMessage contract only admits Literal["system", "user", "assistant", "tool"].
    The 'developer' identifier is NOT a message role; developer-level instructions are task-scoped
    and configured exclusively via runtime.task(instructions=...).
    Valid RuntimeMessage instances with role 'system', 'assistant', or 'tool' are rejected before inference.

    Args:
        input: The input string or RuntimeInput to validate.

    Returns:
        The validated RuntimeInput.

    Raises:
        ContextPolicyError: If input contains any message whose role is not 'user'.
    """
    if isinstance(input, str):
        return RuntimeInput.from_value(input)
    for message in input.messages:
        if message.role != "user":
            raise ContextPolicyError(
                "Under ContextPolicy.RUNTIME, task turns only accept messages with role 'user'; "
                "replaying 'assistant', 'tool', or injecting 'system' messages is prohibited."
            )
    return input


@runtime_checkable
class RuntimeTask(Protocol, Generic[T]):
    """Explicit lifecycle boundary for a task-scoped ephemeral controlled agent."""

    @property
    def id(self) -> str:
        """Provider-neutral, Proteo-generated opaque task identifier.

        Returns:
            The unique task identifier string.
        """

    @property
    def instructions(self) -> str | None:
        """Initial task instructions frozen at task creation (read-only).

        Returns:
            The frozen instruction string or None if none were provided.
        """

    @property
    def state(self) -> TaskState:
        """Current lifecycle state of the task.

        Returns:
            The TaskState enum value (OPEN, CLOSING, or CLOSED).
        """

    @property
    def diagnostics(self) -> tuple[RuntimeDiagnostic, ...]:
        """Snapshot of diagnostics recorded during task operations.

        Returns:
            A tuple of runtime diagnostics recorded on this task.
        """

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[T]:
        """Execute one turn within the task, reusing the task's runtime context.

        Args:
            input: The user turn input string or structured RuntimeInput.
            config: Optional invocation configuration for this turn.
            include_raw: Optional override to include raw provider payloads.

        Returns:
            The runtime result containing output content and metadata.

        Raises:
            SessionBusyError: If another turn is currently running in this task.
            SessionNotFoundError: If the task has been closed or was not found.
            ContextPolicyError: If the input attempts to replay non-user history.
            ConfigurationError: If the invocation config attempts forbidden overrides.
        """

    def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream runtime events for one turn within the task.

        Args:
            input: The user turn input string or structured RuntimeInput.
            config: Optional invocation configuration for this turn.
            include_raw: Optional override to include raw provider payloads.

        Returns:
            An async iterator over projected runtime events.

        Raises:
            SessionBusyError: If another turn is currently running in this task.
            SessionNotFoundError: If the task has been closed or was not found.
            ContextPolicyError: If the input attempts to replay non-user history.
            ConfigurationError: If the invocation config attempts forbidden overrides.
        """

    async def interrupt(self) -> None:
        """Interrupt the currently active turn in this task."""

    async def close(self) -> None:
        """Idempotently discard runtime context and release provider resources."""

    async def __aenter__(self) -> RuntimeTask[T]:
        """Enter the task context manager.

        Returns:
            The task instance.
        """

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit the task context manager, closing the task.

        Args:
            exc_type: The exception type if raised.
            exc_val: The exception value if raised.
            exc_tb: The traceback if raised.
        """
