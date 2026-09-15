"""Session contract for resumable runtime conversations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Generic, Protocol, TypeVar, runtime_checkable

from .events import RuntimeEvent
from .input import RuntimeInput
from .model import InvocationConfig, RuntimeResult
from .session_codec import SessionDescriptor

T = TypeVar("T")


@runtime_checkable
class RuntimeSession(Protocol, Generic[T]):
    """Async-first lifecycle and invocation contract for a session."""

    id: str
    descriptor: SessionDescriptor

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[T]:
        """Invoke a turn in this session."""

    def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Return an asynchronous stream for a session turn."""

    async def interrupt(self) -> None:
        """Request interruption of the active turn."""

    async def close(self) -> None:
        """Close the local session handle while preserving resumable state."""

    async def archive(self) -> None:
        """Archive the session without deleting it."""

    async def delete(self) -> None:
        """Delete the provider session and its local descriptor."""
