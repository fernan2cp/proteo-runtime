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
from .model_info import ModelInfo
from .types import freeze_mapping
from .usage import RuntimeUsage

T = TypeVar("T")

__all__ = [
    "InvocationConfig",
    "RuntimeResult",
    "RuntimeModel",
    "StructuredOutputPolicy",
    "ModelInfo",
    "RuntimeUsage",
]


@dataclass(frozen=True, slots=True)
class InvocationConfig:
    """Immutable provider-neutral invocation options."""

    model: str | None = None
    reasoning_effort: str | None = None
    include_raw: bool | None = None
    timeout_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate timeout and freeze metadata."""

        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class StructuredOutputPolicy:
    """Bounded host validation policy for structured output attempts."""

    max_attempts: int = 2

    def __post_init__(self) -> None:
        """Reject unsafe or meaningless validation attempt limits."""

        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")


@dataclass(frozen=True, slots=True, init=False)
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

    def __init__(
        self,
        value: T | None = None,
        usage: RuntimeUsage | None = None,
        runtime: RuntimeIdentity | None = None,
        model: str = "",
        profile: str = "brain",
        reasoning_effort: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        diagnostics: tuple[RuntimeDiagnostic, ...] = (),
        raw: object | None = None,
        output: T | None = None,
    ) -> None:
        """Initialize a result using legacy `value` or convenience `output`."""

        if value is None and output is not None:
            value = output
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "usage", usage or RuntimeUsage())
        object.__setattr__(self, "runtime", runtime or RuntimeIdentity("unknown", "unknown"))
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "reasoning_effort", reasoning_effort)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "turn_id", turn_id)
        object.__setattr__(self, "diagnostics", tuple(diagnostics))
        object.__setattr__(self, "raw", raw)

    @property
    def output(self) -> T:
        """Return the result value under the Phase 1 terminology."""

        return self.value


@runtime_checkable
class RuntimeModel(Protocol, Generic[T]):
    """Async-first provider-neutral model contract."""

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[T]:
        """Invoke the model once."""

    def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Return an asynchronous event stream."""

    def with_structured_output(
        self,
        schema: type[BaseModel] | dict[str, Any],
        *,
        policy: StructuredOutputPolicy | None = None,
    ) -> RuntimeModel[Any]:
        """Return a model configured for a structured output schema."""

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return capabilities effective for this model configuration."""
