"""Deterministic provider-free runtime implementations for tests."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.diagnostics import RuntimeDiagnostic
from proteo_runtime.core.errors import (
    AgentRuntimeError,
    CancellationError,
    CapabilityError,
    InterruptedError,
    SessionBusyError,
    SessionMismatchError,
    SessionNotFoundError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.input import RuntimeInput
from proteo_runtime.core.model import InvocationConfig, RuntimeResult
from proteo_runtime.core.model_info import ModelInfo
from proteo_runtime.core.profiles import profile_spec
from proteo_runtime.core.session_codec import SessionCodec
from proteo_runtime.core.usage import RuntimeUsage


@dataclass(frozen=True, slots=True)
class FakeTurn:
    """One deterministic scripted fake invocation."""

    value: Any = "fake response"
    usage: RuntimeUsage = field(default_factory=RuntimeUsage)
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()
    events: tuple[RuntimeEvent, ...] = ()
    error: AgentRuntimeError | None = None
    delay_seconds: float = 0.0


@dataclass(slots=True)
class _SessionState:
    """Mutable internal state retained independently of session handles."""

    provider_session_id: str
    descriptor: str
    profile: str
    level: str
    security_policy: str
    archived: bool = False
    deleted: bool = False
    active: bool = False
    interrupted: bool = False
    guard: asyncio.Lock = field(default_factory=asyncio.Lock)


class FakeRuntime:
    """Deterministic runtime with no provider, network, or authentication access."""

    def __init__(
        self,
        turns: Iterable[FakeTurn] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        capabilities: RuntimeCapabilities | None = None,
        identity: RuntimeIdentity | None = None,
    ) -> None:
        """Initialize scripted turns and injectable deterministic dependencies."""

        self._turns = deque(turns or ())
        self._clock = clock or (lambda: datetime.now(UTC))
        self._counter = 0
        self._id_factory = id_factory or self._default_id
        self._identity = identity or RuntimeIdentity("fake", "fake-identity", "Fake Runtime")
        self._capabilities = capabilities or RuntimeCapabilities(
            structured_output=False,
            ephemeral_sessions=True,
            persistent_sessions=True,
            streaming=True,
            interruption=True,
            host_tools=False,
            native_tools=False,
            sandbox=True,
            usage_reporting=True,
        )
        self._sessions: dict[str, _SessionState] = {}
        self._sequence = 0
        self._started = False
        self._closed = False
        self.events: list[RuntimeEvent] = []

    def _default_id(self) -> str:
        """Generate a stable local identifier."""

        self._counter += 1
        return f"fake-{self._counter}"

    def _emit(
        self,
        kind: RuntimeEventKind,
        *,
        invocation_id: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Append and return one correlated monotonic event."""

        event = RuntimeEvent(
            kind=kind,
            event_id=self._id_factory(),
            sequence=self._sequence,
            occurred_at=self._clock(),
            runtime=self._identity,
            invocation_id=invocation_id,
            session_id=session_id,
            turn_id=turn_id,
            metadata=metadata or {},
        )
        self._sequence += 1
        self.events.append(event)
        return event

    async def start(self) -> None:
        """Start the fake runtime and emit a lifecycle event."""

        if not self._started:
            self._started = True
            self._closed = False
            self._emit(RuntimeEventKind.RUNTIME_STARTED)

    async def close(self) -> None:
        """Close the fake runtime while preserving session state."""

        if self._started and not self._closed:
            self._closed = True
            self._emit(RuntimeEventKind.RUNTIME_STOPPED)

    async def capabilities(self) -> RuntimeCapabilities:
        """Return fake runtime capabilities."""

        return self._capabilities

    async def models(self) -> list[ModelInfo]:
        """Return one deterministic model descriptor."""

        return [
            ModelInfo(
                "fake-model", "Fake Model", ("low", "medium", "high", "ultra"), self._capabilities
            )
        ]

    def model(self, *, profile: str, level: str = "medium") -> FakeRuntimeModel:
        """Create a fake model view for a profile and level."""

        profile_spec(profile)
        if level not in {"low", "medium", "high", "ultra"}:
            raise CapabilityError(f"Unknown reasoning level: {level}")
        return FakeRuntimeModel(self, profile, level)

    async def session(self, *, profile: str = "session") -> FakeRuntimeSession:
        """Create and retain a resumable fake session."""

        spec = profile_spec(profile)
        provider_id = self._id_factory()
        descriptor = SessionCodec.encode(
            provider="fake",
            provider_session_id=provider_id,
            identity_fingerprint=self._identity.fingerprint,
            configuration_fingerprint=f"{profile}:medium",
            profile=profile,
            level="medium",
            context_policy=spec.context.value,
            security_policy=spec.security_policy,
        )
        state = _SessionState(provider_id, descriptor, profile, "medium", spec.security_policy)
        self._sessions[descriptor] = state
        self._emit(RuntimeEventKind.SESSION_CREATED, session_id=descriptor)
        return FakeRuntimeSession(self, state)

    async def resume_session(self, session_id: str) -> FakeRuntimeSession:
        """Resume a retained fake session after validating its descriptor."""

        descriptor = SessionCodec.decode(session_id)
        if (
            descriptor.provider != "fake"
            or descriptor.identity_fingerprint != self._identity.fingerprint
        ):
            raise SessionMismatchError("Session identity does not match this fake runtime")
        state = self._sessions.get(session_id)
        if state is None or state.deleted:
            raise SessionNotFoundError("Fake session was not found")
        self._emit(RuntimeEventKind.SESSION_RESUMED, session_id=session_id)
        return FakeRuntimeSession(self, state)

    async def migrate_session(
        self,
        session_id: str,
        *,
        profile: str,
        level: str = "medium",
        security_policy: str,
    ) -> FakeRuntimeSession:
        """Migrate a fake session within the same provider identity."""

        old = SessionCodec.decode(session_id)
        if old.provider != "fake" or old.identity_fingerprint != self._identity.fingerprint:
            raise SessionMismatchError("Only same-identity fake sessions can migrate")
        current = self._sessions.get(session_id)
        if current is None or current.deleted:
            raise SessionNotFoundError("Fake session was not found")
        profile_spec(profile)
        if level not in {"low", "medium", "high", "ultra"}:
            raise CapabilityError(f"Unknown reasoning level: {level}")
        descriptor = SessionCodec.encode(
            provider="fake",
            provider_session_id=old.provider_session_id,
            identity_fingerprint=self._identity.fingerprint,
            configuration_fingerprint=f"{profile}:{level}",
            profile=profile,
            level=level,
            context_policy=profile_spec(profile).context.value,
            security_policy=security_policy,
        )
        self._sessions[descriptor] = current
        current.descriptor = descriptor
        current.profile = profile
        current.level = level
        current.security_policy = security_policy
        return FakeRuntimeSession(self, current)

    async def _claim(self, state: _SessionState) -> None:
        """Atomically claim a session turn or fail immediately."""

        async with state.guard:
            if state.active:
                raise SessionBusyError("A turn is already active for this session")
            state.active = True
            state.interrupted = False

    async def _release(self, state: _SessionState) -> None:
        """Release a session turn claim."""

        async with state.guard:
            state.active = False

    def _next_turn(self) -> FakeTurn:
        """Pop the next scripted turn or return a default response."""

        return self._turns.popleft() if self._turns else FakeTurn()

    async def _execute(
        self,
        input: RuntimeInput,
        *,
        model: str,
        profile: str,
        level: str,
        state: _SessionState | None = None,
        keep_active: bool = False,
    ) -> tuple[RuntimeResult[Any], list[RuntimeEvent], FakeTurn]:
        """Execute one scripted turn and collect events for invocation or stream."""

        del input
        if state is not None:
            await self._claim(state)
        invocation_id = self._id_factory()
        turn_id = self._id_factory()
        session_id = state.descriptor if state else None
        generated = [
            self._emit(
                RuntimeEventKind.INVOCATION_STARTED,
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
            ),
            self._emit(
                RuntimeEventKind.TURN_STARTED,
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
            ),
        ]
        turn = self._next_turn()
        try:
            if turn.delay_seconds:
                await asyncio.sleep(turn.delay_seconds)
            if state and state.interrupted:
                self._emit(
                    RuntimeEventKind.INTERRUPTED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
                raise InterruptedError("Fake turn was interrupted")
            if turn.error:
                self._emit(
                    RuntimeEventKind.INVOCATION_FAILED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
                raise turn.error
            result = RuntimeResult(
                value=turn.value,
                usage=turn.usage,
                runtime=self._identity,
                model=model,
                profile=profile,
                reasoning_effort=level,
                session_id=session_id,
                turn_id=turn_id,
                diagnostics=turn.diagnostics,
            )
            generated.append(
                self._emit(
                    RuntimeEventKind.TOKEN_USAGE_UPDATED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    metadata={"total_tokens": turn.usage.total_tokens or 0},
                )
            )
            generated.append(
                self._emit(
                    RuntimeEventKind.TURN_COMPLETED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            )
            generated.append(
                self._emit(
                    RuntimeEventKind.INVOCATION_COMPLETED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            )
            return result, generated, turn
        except asyncio.CancelledError as exc:
            self._emit(
                RuntimeEventKind.CANCELLED,
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
            )
            raise CancellationError("Fake turn was cancelled") from exc
        finally:
            if state is not None and not keep_active:
                await self._release(state)


class FakeRuntimeModel:
    """Model facade backed by a :class:`FakeRuntime`."""

    def __init__(self, runtime: FakeRuntime, profile: str, level: str) -> None:
        """Store the runtime and selected profile."""

        self.runtime = runtime
        self.profile = profile
        self.level = level

    async def ainvoke(
        self, input: RuntimeInput, *, config: InvocationConfig | None = None
    ) -> RuntimeResult[Any]:
        """Invoke one deterministic fake turn."""

        normalized = RuntimeInput.from_value(input)
        selected = config.model if config and config.model else "fake-model"
        return (
            await self.runtime._execute(
                normalized, model=selected, profile=self.profile, level=self.level
            )
        )[0]

    async def astream(
        self, input: RuntimeInput, *, config: InvocationConfig | None = None
    ) -> AsyncIterator[RuntimeEvent]:
        """Yield deterministic lifecycle and output-delta events."""

        normalized = RuntimeInput.from_value(input)
        result, generated, turn = await self.runtime._execute(
            normalized, model="fake-model", profile=self.profile, level=self.level
        )
        del result
        streamed = list(generated)
        if turn.events:
            streamed.extend(turn.events)
        else:
            streamed.extend(
                self.runtime._emit(RuntimeEventKind.OUTPUT_TEXT_DELTA, metadata={"text": chunk})
                for chunk in _chunks(str(turn.value))
            )
        for event in sorted(streamed, key=lambda item: item.sequence):
            yield event

    def with_structured_output(self, schema: type[Any] | dict[str, Any]) -> FakeRuntimeModel:
        """Reject structured output because the fake advertises no support."""

        del schema
        raise CapabilityError("Fake runtime does not implement structured output")

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return capabilities of the underlying fake runtime."""

        return await self.runtime.capabilities()


class FakeRuntimeSession:
    """Resumable fake session handle."""

    def __init__(self, runtime: FakeRuntime, state: _SessionState) -> None:
        """Bind a handle to retained session state."""

        self._runtime = runtime
        self._state = state
        self.id = state.descriptor
        self._closed = False

    async def ainvoke(
        self, input: RuntimeInput, *, config: InvocationConfig | None = None
    ) -> RuntimeResult[Any]:
        """Invoke one turn while enforcing single-active-turn semantics."""

        if self._closed or self._state.deleted:
            raise SessionNotFoundError("Session handle is closed or deleted")
        normalized = RuntimeInput.from_value(input)
        return (
            await self._runtime._execute(
                normalized,
                model="fake-session",
                profile=self._state.profile,
                level=self._state.level,
                state=self._state,
            )
        )[0]

    async def astream(
        self, input: RuntimeInput, *, config: InvocationConfig | None = None
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream one session turn with ordered fake events."""

        if self._closed or self._state.deleted:
            raise SessionNotFoundError("Session handle is closed or deleted")
        normalized = RuntimeInput.from_value(input)
        result, generated, turn = await self._runtime._execute(
            normalized,
            model="fake-session",
            profile=self._state.profile,
            level=self._state.level,
            state=self._state,
            keep_active=True,
        )
        del result
        streamed = list(generated)
        if turn.events:
            streamed.extend(turn.events)
        else:
            streamed.extend(
                self._runtime._emit(RuntimeEventKind.OUTPUT_TEXT_DELTA, metadata={"text": chunk})
                for chunk in _chunks(str(turn.value))
            )
        for event in sorted(streamed, key=lambda item: item.sequence):
            yield event

    async def interrupt(self) -> None:
        """Request interruption of the active session turn."""

        async with self._state.guard:
            if self._state.active:
                self._state.interrupted = True

    async def close(self) -> None:
        """Close this handle while retaining its resumable state."""

        self._closed = True

    async def archive(self) -> None:
        """Archive this session without deleting retained state."""

        self._state.archived = True

    async def delete(self) -> None:
        """Delete this session from the fake runtime."""

        self._state.deleted = True
        self._runtime._sessions.pop(self.id, None)
        self._closed = True


def _chunks(value: str, size: int = 8) -> tuple[str, ...]:
    """Split text into deterministic output chunks."""

    return tuple(value[index : index + size] for index in range(0, len(value), size))
