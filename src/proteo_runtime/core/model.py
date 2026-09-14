"""Model and invocation contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from .capabilities import RuntimeCapabilities
from .diagnostics import RuntimeDiagnostic
from .events import RuntimeEvent
from .identity import RuntimeIdentity
from .input import RuntimeInput
from .types import freeze_mapping
from .usage import RuntimeUsage

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class InvocationConfig:
    """Immutable provider-neutral invocation options."""

    model: str | None = None
    reasoning_effort: str | None = None
    include_raw: bool = False
    timeout_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate timeout and freeze metadata."""

        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class RuntimeResult(Generic[T]):
    """Immutable result returned from an invocation."""

    value: T
    usage: RuntimeUsage
    runtime: RuntimeIdentity
    model: str
    profile: str
    reasoning_effort: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()
    raw: object | None = None

    def __post_init__(self) -> None:
        """Normalize diagnostics and prevent mutable diagnostic collections."""

        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@runtime_checkable
class RuntimeModel(Protocol, Generic[T]):
    """Async-first provider-neutral model contract."""

    async def ainvoke(
        self, input: RuntimeInput, *, config: InvocationConfig | None = None
    ) -> RuntimeResult[T]:
        """Invoke the model once."""

    def astream(
        self, input: RuntimeInput, *, config: InvocationConfig | None = None
    ) -> AsyncIterator[RuntimeEvent]:
        """Return an asynchronous event stream."""

    def with_structured_output(self, schema: type[BaseModel] | dict[str, Any]) -> RuntimeModel[Any]:
        """Return a model configured for a structured output schema."""

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return capabilities effective for this model configuration."""
