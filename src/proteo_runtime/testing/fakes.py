"""Deterministic provider-free runtime implementations for tests."""

from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ValidationError

from proteo_runtime.config import RuntimeConfigV1
from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.diagnostics import RuntimeDiagnostic
from proteo_runtime.core.errors import (
    AgentRuntimeError,
    CancellationError,
    CapabilityError,
    ConfigurationError,
    ContextPolicyError,
    InterruptedError,
    RuntimeUnavailableError,
    SessionBusyError,
    SessionMismatchError,
    SessionNotFoundError,
    StructuredOutputError,
    TransportError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.input import RuntimeInput
from proteo_runtime.core.model import InvocationConfig, RuntimeResult, StructuredOutputPolicy
from proteo_runtime.core.model_info import ModelInfo
from proteo_runtime.core.observability import ObservabilityStatus
from proteo_runtime.core.profiles import profile_spec
from proteo_runtime.core.session_codec import SessionCodec
from proteo_runtime.core.task import RuntimeTask, TaskState, validate_task_input
from proteo_runtime.core.usage import RuntimeUsage
from proteo_runtime.observability import ObservabilityConfig, RuntimeEventBus
from proteo_runtime.tools import ToolExecutor, ToolRegistry, ToolRequest, ToolSnapshot


@dataclass(frozen=True, slots=True)
class FakeTurn:
    """One deterministic scripted fake invocation."""

    value: Any = "fake response"
    usage: RuntimeUsage = field(default_factory=RuntimeUsage)
    diagnostics: tuple[RuntimeDiagnostic, ...] = ()
    events: tuple[RuntimeEvent, ...] = ()
    error: Exception | None = None
    delay_seconds: float = 0.0
    missing_terminal: bool = False
    tool_calls: tuple[tuple[str, str, Mapping[str, Any]], ...] = ()


@dataclass(slots=True)
class _SessionState:
    """Mutable internal state retained independently of session handles."""

    provider_session_id: str
    descriptor: str
    profile: str
    level: str
    security_policy: str
    context_policy: str
    archived: bool = False
    deleted: bool = False
    active: bool = False
    interrupted: bool = False
    guard: asyncio.Lock = field(default_factory=asyncio.Lock)
    generation: int = 0
    tool_snapshot: ToolSnapshot | None = None
    tool_executor: ToolExecutor | None = None


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
        observability: ObservabilityConfig | None = None,
        config: RuntimeConfigV1 | None = None,
    ) -> None:
        """Initialize scripted turns and injectable deterministic dependencies."""

        self._turns = deque(turns or ())
        self._clock = clock or (lambda: datetime.now(UTC))
        self._counter = 0
        self._id_factory = id_factory or self._default_id
        self._identity = identity or RuntimeIdentity("fake", "fake-identity", "Fake Runtime")
        self._config = config
        self._capabilities = capabilities or RuntimeCapabilities(
            structured_output=True,
            ephemeral_sessions=True,
            ephemeral_tasks=True,
            persistent_sessions=True,
            streaming=True,
            interruption=True,
            host_tools=True,
            native_tools=False,
            sandbox=True,
            usage_reporting=True,
        )
        self._sessions: dict[str, _SessionState] = {}
        self._tasks: dict[str, FakeTask] = {}
        self._deleted_sessions: set[str] = set()
        self._sequence = 0
        self._started = False
        self._closed = False
        self.events: list[RuntimeEvent] = []
        self._observability = RuntimeEventBus(observability)

    def observability_status(self) -> ObservabilityStatus:
        """Return the aggregate health of configured observers."""

        return self._observability.status

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
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        result: RuntimeResult[Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Append and return one correlated monotonic event."""

        event = RuntimeEvent(
            kind,
            self._id_factory(),
            self._sequence,
            self._clock(),
            self._identity,
            invocation_id,
            session_id,
            turn_id,
            metadata or {},
            result,
            payload or {},
            task_id=task_id,
        )
        self._sequence += 1
        self.events.append(event)
        return event

    async def start(self) -> None:
        """Start the fake runtime and emit a lifecycle event."""

        if not self._started:
            self._started = True
            self._closed = False
            try:
                await self._dispatch(self._emit(RuntimeEventKind.RUNTIME_STARTED))
            except AgentRuntimeError:
                with suppress(AgentRuntimeError):
                    await self.close()
                raise

    async def __aenter__(self) -> FakeRuntime:
        """Start the runtime and return it for async context manager use."""

        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Close the runtime when leaving an async context manager."""

        del exc_type, exc_value, traceback
        await self.close()

    @property
    def name(self) -> str:
        """Return the runtime provider name."""

        return "fake"

    async def close(self) -> None:
        """Close the fake runtime while preserving session state."""

        if not self._closed:
            self._closed = True
            for task in list(self._tasks.values()):
                with suppress(Exception):
                    await task.close()
            self._tasks.clear()
            if self._started:
                observability_error: AgentRuntimeError | None = None
                try:
                    await self._dispatch(self._emit(RuntimeEventKind.RUNTIME_STOPPED))
                except AgentRuntimeError as exc:
                    observability_error = exc
                try:
                    await self._observability.close()
                except AgentRuntimeError as exc:
                    observability_error = observability_error or exc
                if observability_error is not None:
                    raise observability_error

    async def capabilities(self) -> RuntimeCapabilities:
        """Return fake runtime capabilities."""

        return self._capabilities

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return the fake runtime capabilities."""

        return await self.capabilities()

    async def models(self) -> list[ModelInfo]:
        """Return one deterministic model descriptor."""

        return [
            ModelInfo(
                "fake-model", "Fake Model", ("low", "medium", "high", "ultra"), self._capabilities
            )
        ]

    def model(self, *, profile: str, level: str = "medium") -> FakeRuntimeModel:
        """Create a fake model view for a profile and level."""

        spec = self._profile_spec(profile)
        if spec.context.value == "runtime" and spec.lifecycle.value == "ephemeral":
            raise CapabilityError(
                f"Profile '{profile}' has runtime context and requires an explicit task lifecycle "
                f"via runtime.task(); use 'controlled_turn' for invocation-scoped model execution."
            )
        if spec.persistent or spec.lifecycle.value in {"explicit", "persistent"}:
            raise CapabilityError(
                f"Profile '{profile}' is persistent; use runtime.session() for durable sessions."
            )
        if level not in {"low", "medium", "high", "ultra"}:
            raise CapabilityError(f"Unknown reasoning level: {level}")
        return FakeRuntimeModel(self, profile, level)

    async def session(
        self,
        profile: str = "session",
        *,
        level: str = "medium",
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> FakeRuntimeSession:
        """Create and retain a resumable fake session."""

        spec = self._profile_spec(profile)
        if spec.lifecycle.value == "ephemeral":
            if spec.context.value == "runtime":
                raise CapabilityError(
                    f"Profile '{profile}' is ephemeral; use runtime.task() for ephemeral task execution"
                )
            raise CapabilityError(
                f"Profile '{profile}' is ephemeral and external; use runtime.model() for invocation-scoped execution"
            )
        if not spec.persistent:
            raise CapabilityError("Fake persistent sessions require a persistent profile")
        if level not in {"low", "medium", "high", "ultra"}:
            raise CapabilityError(f"Unknown reasoning level: {level}")
        tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
        provider_id = self._id_factory()
        descriptor = SessionCodec.encode(
            provider="fake",
            provider_session_id=provider_id,
            identity_fingerprint=self._identity.fingerprint,
            configuration_fingerprint=f"{profile}:{level}",
            profile=profile,
            level=level,
            context_policy=spec.context.value,
            security_policy=spec.security_policy,
        )
        state = _SessionState(
            provider_id,
            descriptor,
            profile,
            level,
            spec.security_policy.value,
            spec.context.value,
            tool_snapshot=tool_snapshot,
            tool_executor=tool_executor,
        )
        self._sessions[descriptor] = state
        await self._dispatch(self._emit(RuntimeEventKind.SESSION_CREATED, session_id=descriptor))
        return FakeRuntimeSession(self, state)

    async def resume_session(
        self,
        session_id: str,
        *,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> FakeRuntimeSession:
        """Resume a retained fake session after validating its descriptor."""

        if not isinstance(session_id, str):
            raise TypeError("Session descriptor must be a string")
        if session_id.startswith("task_"):
            raise SessionNotFoundError(
                f"Task '{session_id}' is ephemeral and cannot be resumed as a session"
            )
        if session_id in self._deleted_sessions:
            raise SessionNotFoundError("Fake session was not found")
        descriptor = SessionCodec.decode(session_id)
        if (
            descriptor.provider != "fake"
            or descriptor.identity_fingerprint != self._identity.fingerprint
        ):
            raise SessionMismatchError("Session identity does not match this fake runtime")
        spec = self._profile_spec(descriptor.profile)
        tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
        if (
            descriptor.context_policy != spec.context.value
            or descriptor.security_policy != spec.security_policy.value
        ):
            raise SessionMismatchError("Session policy does not match this fake runtime")
        state = self._sessions.get(session_id)
        if state is not None and state.deleted:
            state = None
        if state is not None and state.active:
            raise SessionBusyError("Fake session already has an active turn")
        if state is None:
            state = _SessionState(
                descriptor.provider_session_id,
                session_id,
                descriptor.profile,
                descriptor.level,
                spec.security_policy.value,
                spec.context.value,
                tool_snapshot=tool_snapshot,
                tool_executor=tool_executor,
            )
            self._sessions[session_id] = state
        else:
            state.generation += 1
            state.tool_snapshot = tool_snapshot
            state.tool_executor = tool_executor
        await self._dispatch(self._emit(RuntimeEventKind.SESSION_RESUMED, session_id=session_id))
        return FakeRuntimeSession(self, state)

    async def task(
        self,
        profile: str = "controlled_agent",
        *,
        level: str = "medium",
        instructions: str | None = None,
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> FakeTask:
        """Create a task-scoped ephemeral controlled agent.

        Args:
            profile: Profile name (defaults to 'controlled_agent').
            level: Logical reasoning effort level.
            instructions: Optional initial instructions frozen for the task lifetime.
            config: Optional default invocation configuration for turns.
            registry: Host-tool registry (mandatory for controlled tool profiles).
            executor: Optional host-tool executor.

        Returns:
            An active FakeTask handle.

        Raises:
            CapabilityError: If capabilities, lifecycle, or tool bindings are invalid.
        """
        capabilities = await self.capabilities()
        if not capabilities.ephemeral_tasks:
            raise CapabilityError(
                f"Runtime '{self.name}' does not support ephemeral multi-turn tasks."
            )
        spec = self._profile_spec(profile)
        if spec.context.value == "external":
            raise CapabilityError(
                f"Profile '{profile}' has external context; use runtime.model() for invocation-scoped execution"
            )
        if spec.persistent or spec.lifecycle.value == "persistent":
            raise CapabilityError(
                f"Profile '{profile}' is persistent; use runtime.session() for durable sessions"
            )
        if registry is None:
            raise CapabilityError("A host-tool registry is required for this profile")
        tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
        task_id = f"task_{uuid4().hex}"
        task = FakeTask(
            runtime=self,
            task_id=task_id,
            profile=profile,
            level=level,
            instructions=instructions,
            config=config or InvocationConfig(),
            tool_snapshot=tool_snapshot,
            tool_executor=tool_executor,
        )
        self._tasks[task_id] = task
        await self._dispatch(self._emit(RuntimeEventKind.TASK_STARTED, task_id=task_id))
        return task

    def get_task(self, task_id: str) -> FakeTask:
        """Resolve an active, in-memory task by its identifier.

        Args:
            task_id: Unique task identifier.

        Returns:
            The active FakeTask instance.

        Raises:
            SessionNotFoundError: If the task is missing or already closed.
        """
        task = self._tasks.get(task_id)
        if task is None or task._state != TaskState.OPEN:
            raise SessionNotFoundError(f"Task '{task_id}' not found or already closed")
        return task

    def _tool_binding(
        self,
        spec: Any,
        registry: ToolRegistry | None,
        executor: ToolExecutor | None,
    ) -> tuple[ToolSnapshot | None, ToolExecutor | None]:
        """Validate a fake host-tool binding without executing provider code."""

        if registry is None and executor is None:
            if spec.host_tools.value != "disabled":
                raise CapabilityError("A host-tool registry is required for this profile")
            return None, None
        if not self._capabilities.host_tools:
            raise CapabilityError("Fake runtime host tools are disabled")
        if spec.host_tools.value not in {"controlled", "explicit"}:
            raise CapabilityError("The selected profile does not permit host-managed tools")
        if registry is not None:
            snapshot = registry.snapshot()
        else:
            assert executor is not None
            snapshot = executor.snapshot
        if executor is None:
            executor = ToolExecutor(snapshot)
        elif executor.snapshot.provider_definitions() != snapshot.provider_definitions():
            raise CapabilityError("Tool executor does not match the registry snapshot")
        if not snapshot.definitions():
            raise CapabilityError("A host-tool registry must contain at least one tool")
        return snapshot, executor

    def _profile_spec(self, profile: str) -> Any:
        """Resolve built-in or configured custom profile semantics."""

        if self._config is not None:
            return self._config.profile_spec(profile)
        return profile_spec(profile)

    async def migrate_session(
        self,
        session_id: str,
        *,
        profile: str,
        level: str = "medium",
        security_policy: str,
    ) -> FakeRuntimeSession:
        """Migrate a fake session while preserving its provider identity."""

        old = SessionCodec.decode(session_id)
        if old.provider != "fake" or old.identity_fingerprint != self._identity.fingerprint:
            raise SessionMismatchError("Only same-identity fake sessions can migrate")
        current = self._sessions.get(session_id)
        if current is not None and current.deleted:
            current = None
        if current is not None and current.active:
            raise SessionBusyError("Cannot migrate an active fake session")
        if level not in {"low", "medium", "high", "ultra"}:
            raise CapabilityError(f"Unknown reasoning level: {level}")
        spec = self._profile_spec(profile)
        if not spec.persistent:
            raise CapabilityError("Fake session migration requires a persistent profile")
        if security_policy != old.security_policy or security_policy != spec.security_policy.value:
            raise CapabilityError("Session migration cannot expand or change permissions")
        descriptor = SessionCodec.encode(
            provider="fake",
            provider_session_id=old.provider_session_id,
            identity_fingerprint=self._identity.fingerprint,
            configuration_fingerprint=f"{profile}:{level}",
            profile=profile,
            level=level,
            context_policy=spec.context.value,
            security_policy=security_policy,
            descriptor_nonce=self._id_factory(),
        )
        if current is None:
            current = _SessionState(
                old.provider_session_id,
                descriptor,
                profile,
                level,
                security_policy,
                spec.context.value,
            )
        else:
            self._sessions.pop(session_id, None)
            current.descriptor = descriptor
            current.profile = profile
            current.level = level
            current.security_policy = security_policy
            current.context_policy = spec.context.value
            current.generation += 1
        self._sessions[descriptor] = current
        await self._dispatch(
            self._emit(
                RuntimeEventKind.SESSION_MIGRATED,
                session_id=descriptor,
                metadata={
                    "old_session_id": session_id,
                    "new_session_id": descriptor,
                    "old_profile": old.profile,
                    "new_profile": profile,
                    "old_level": old.level,
                    "new_level": level,
                },
            )
        )
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

    async def _dispatch(self, event: RuntimeEvent) -> RuntimeEvent:
        """Dispatch one event through the shared observer bus."""

        return await self._observability.emit(event)

    async def _publish_events(self, events: list[RuntimeEvent]) -> list[RuntimeEvent]:
        """Dispatch a sequence and retain any terminal result enrichment."""

        published: list[RuntimeEvent] = []
        for event in events:
            published_event = await self._dispatch(event)
            published.append(published_event)
        return published

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
        stream: bool = False,
        invocation_metadata: Mapping[str, Any] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> tuple[RuntimeResult[Any], list[RuntimeEvent], FakeTurn]:
        """Execute one scripted turn and collect lifecycle events."""

        del input
        claimed = False
        completed = False
        generated: list[RuntimeEvent] = []
        published = False
        invocation_id, turn_id = self._id_factory(), self._id_factory()
        session_id = state.descriptor if state else None
        try:
            if state is not None:
                await self._claim(state)
                claimed = True
            generated = [
                self._emit(
                    RuntimeEventKind.INVOCATION_STARTED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    metadata={
                        **dict(invocation_metadata or {}),
                        "model": model,
                        "profile": profile,
                        "reasoning_effort": level,
                        "ephemeral": state is None,
                        "structured_output": profile == "structured",
                        "context_policy": state.context_policy if state else None,
                        "security_policy": state.security_policy if state else None,
                    },
                ),
                self._emit(
                    RuntimeEventKind.TURN_STARTED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                ),
            ]
            turn = self._next_turn()
            if tool_executor is not None and turn.tool_calls:
                event_start = len(tool_executor.events)
                for call_id, tool_name, arguments in turn.tool_calls:
                    await tool_executor.execute(
                        ToolRequest(
                            invocation_id,
                            call_id,
                            tool_name,
                            arguments,
                            session_id=session_id,
                            turn_id=turn_id,
                        )
                    )
                generated.extend(tool_executor.events[event_start:])
            if turn.delay_seconds:
                await asyncio.sleep(turn.delay_seconds)
            if state and state.interrupted:
                generated.extend(
                    [
                        self._emit(
                            RuntimeEventKind.TURN_INTERRUPTED,
                            invocation_id=invocation_id,
                            session_id=session_id,
                            turn_id=turn_id,
                        ),
                        self._emit(
                            RuntimeEventKind.INTERRUPTED,
                            invocation_id=invocation_id,
                            session_id=session_id,
                            turn_id=turn_id,
                        ),
                    ]
                )
                raise InterruptedError("Fake turn was interrupted")
            if turn.error:
                if isinstance(turn.error, InterruptedError):
                    generated.extend(
                        [
                            self._emit(
                                RuntimeEventKind.TURN_INTERRUPTED,
                                invocation_id=invocation_id,
                                session_id=session_id,
                                turn_id=turn_id,
                            ),
                            self._emit(
                                RuntimeEventKind.INTERRUPTED,
                                invocation_id=invocation_id,
                                session_id=session_id,
                                turn_id=turn_id,
                            ),
                        ]
                    )
                else:
                    generated.extend(
                        [
                            self._emit(
                                RuntimeEventKind.TURN_FAILED,
                                invocation_id=invocation_id,
                                session_id=session_id,
                                turn_id=turn_id,
                            ),
                            self._emit(
                                RuntimeEventKind.INVOCATION_FAILED,
                                invocation_id=invocation_id,
                                session_id=session_id,
                                turn_id=turn_id,
                            ),
                        ]
                    )
                if isinstance(turn.error, AgentRuntimeError):
                    raise turn.error
                raise RuntimeUnavailableError(
                    "Fake turn failed", details={"exception_type": type(turn.error).__name__}
                ) from None
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
            if not stream:
                generated.extend(
                    self._terminal_events(invocation_id, session_id, turn_id, turn.usage, result)
                )
                generated = await self._publish_events(generated)
                published = True
                terminal = next(
                    (event.result for event in reversed(generated) if event.result is not None),
                    None,
                )
                if terminal is not None:
                    result = terminal
            completed = True
            return result, generated, turn
        except asyncio.CancelledError as exc:
            generated.append(
                self._emit(
                    RuntimeEventKind.CANCELLED,
                    invocation_id=invocation_id,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            )
            if not published:
                await self._publish_events(generated)
            raise CancellationError("Fake turn was cancelled") from exc
        except Exception:
            if not published and generated:
                await self._publish_events(generated)
            raise
        finally:
            if state is not None and claimed and (not keep_active or not completed):
                await self._release(state)
            if tool_executor is not None and not keep_active:
                tool_executor.end_invocation(invocation_id)

    def _terminal_events(
        self,
        invocation_id: str,
        session_id: str | None,
        turn_id: str,
        usage: RuntimeUsage,
        result: RuntimeResult[Any] | None = None,
        *,
        task_id: str | None = None,
    ) -> list[RuntimeEvent]:
        """Emit usage and completion events for a successful invocation."""

        return [
            self._emit(
                RuntimeEventKind.TOKEN_USAGE_UPDATED,
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
                task_id=task_id,
                metadata={"total_tokens": usage.total_tokens or 0},
            ),
            self._emit(
                RuntimeEventKind.TURN_COMPLETED,
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
                task_id=task_id,
            ),
            self._emit(
                RuntimeEventKind.INVOCATION_COMPLETED,
                invocation_id=invocation_id,
                session_id=session_id,
                turn_id=turn_id,
                task_id=task_id,
                result=result,
            ),
        ]

    async def _execute_task_turn(
        self,
        task: FakeTask,
        input: RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
        stream: bool = False,
    ) -> tuple[RuntimeResult[Any], list[RuntimeEvent], FakeTurn]:
        """Execute one scripted turn within a task and collect lifecycle events."""

        del input, include_raw
        invocation_id, turn_id = self._id_factory(), self._id_factory()
        task._active_invocation_id = invocation_id
        generated: list[RuntimeEvent] = []
        published = False
        try:
            generated = [
                self._emit(
                    RuntimeEventKind.INVOCATION_STARTED,
                    invocation_id=invocation_id,
                    turn_id=turn_id,
                    task_id=task.id,
                    metadata={
                        **dict(config.metadata if config else {}),
                        "model": task._model,
                        "profile": task._profile,
                        "reasoning_effort": task._level,
                        "ephemeral": True,
                        "structured_output": False,
                        "context_policy": "runtime",
                        "security_policy": "controlled_tools",
                    },
                ),
                self._emit(
                    RuntimeEventKind.TURN_STARTED,
                    invocation_id=invocation_id,
                    turn_id=turn_id,
                    task_id=task.id,
                ),
            ]
            turn = self._next_turn()
            if task._tool_executor is not None and turn.tool_calls:
                event_start = len(task._tool_executor.events)
                for call_id, tool_name, arguments in turn.tool_calls:
                    await task._tool_executor.execute(
                        ToolRequest(
                            invocation_id,
                            call_id,
                            tool_name,
                            arguments,
                            session_id=None,
                            turn_id=turn_id,
                            task_id=task.id,
                        )
                    )
                generated.extend(task._tool_executor.events[event_start:])
            if turn.delay_seconds:
                await asyncio.sleep(turn.delay_seconds)
            if task._interrupted:
                generated.extend(
                    [
                        self._emit(
                            RuntimeEventKind.TURN_INTERRUPTED,
                            invocation_id=invocation_id,
                            turn_id=turn_id,
                            task_id=task.id,
                        ),
                        self._emit(
                            RuntimeEventKind.INTERRUPTED,
                            invocation_id=invocation_id,
                            turn_id=turn_id,
                            task_id=task.id,
                        ),
                    ]
                )
                raise InterruptedError("Fake turn was interrupted")
            if turn.error:
                if isinstance(turn.error, InterruptedError):
                    generated.extend(
                        [
                            self._emit(
                                RuntimeEventKind.TURN_INTERRUPTED,
                                invocation_id=invocation_id,
                                turn_id=turn_id,
                                task_id=task.id,
                            ),
                            self._emit(
                                RuntimeEventKind.INTERRUPTED,
                                invocation_id=invocation_id,
                                turn_id=turn_id,
                                task_id=task.id,
                            ),
                        ]
                    )
                else:
                    generated.extend(
                        [
                            self._emit(
                                RuntimeEventKind.TURN_FAILED,
                                invocation_id=invocation_id,
                                turn_id=turn_id,
                                task_id=task.id,
                            ),
                            self._emit(
                                RuntimeEventKind.INVOCATION_FAILED,
                                invocation_id=invocation_id,
                                turn_id=turn_id,
                                task_id=task.id,
                            ),
                        ]
                    )
                if isinstance(turn.error, AgentRuntimeError):
                    raise turn.error
                raise RuntimeUnavailableError(
                    "Fake turn failed", details={"exception_type": type(turn.error).__name__}
                ) from None
            result = RuntimeResult(
                value=turn.value,
                usage=turn.usage,
                runtime=self._identity,
                model=task._model,
                profile=task._profile,
                reasoning_effort=task._level,
                session_id=None,
                task_id=task.id,
                turn_id=turn_id,
                diagnostics=turn.diagnostics,
            )
            if not stream:
                generated.extend(
                    self._terminal_events(
                        invocation_id, None, turn_id, turn.usage, result, task_id=task.id
                    )
                )
                generated = await self._publish_events(generated)
                published = True
                terminal = next(
                    (event.result for event in reversed(generated) if event.result is not None),
                    None,
                )
                if terminal is not None:
                    result = terminal
            return result, generated, turn
        except asyncio.CancelledError as exc:
            generated.append(
                self._emit(
                    RuntimeEventKind.CANCELLED,
                    invocation_id=invocation_id,
                    turn_id=turn_id,
                    task_id=task.id,
                )
            )
            if not published:
                await self._publish_events(generated)
            raise CancellationError("Fake turn was cancelled") from exc
        except Exception:
            if not published and generated:
                await self._publish_events(generated)
            raise
        finally:
            if task._tool_executor is not None:
                task._tool_executor.end_invocation(invocation_id)
            task._active_invocation_id = None


class FakeRuntimeModel:
    """Model facade backed by a :class:`FakeRuntime`."""

    def __init__(
        self,
        runtime: FakeRuntime,
        profile: str,
        level: str,
        tool_snapshot: ToolSnapshot | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Store the runtime and selected profile."""

        self.runtime, self.profile, self.level = runtime, profile, level
        self._tool_snapshot = tool_snapshot
        self._tool_executor = tool_executor

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[Any]:
        """Invoke one deterministic fake turn."""

        normalized = RuntimeInput.from_value(input)
        if self.profile == "structured":
            raise ConfigurationError(
                "Structured profile requires an output schema", path="output_schema"
            )
        selected = config.model if config and config.model else "fake-model"
        return (
            await self.runtime._execute(
                normalized,
                model=selected,
                profile=self.profile,
                level=self.level,
                invocation_metadata=config.metadata if config is not None else None,
                tool_executor=self._tool_executor,
            )
        )[0]

    async def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Yield deterministic lifecycle, output, usage, and completion events."""

        normalized = RuntimeInput.from_value(input)
        result, generated, turn = await self.runtime._execute(
            normalized,
            model="fake-model",
            profile=self.profile,
            level=self.level,
            stream=True,
            invocation_metadata=config.metadata if config is not None else None,
            tool_executor=self._tool_executor,
        )
        del result, include_raw
        invocation_id, turn_id = generated[0].invocation_id or "", generated[0].turn_id or ""
        streamed = list(generated)
        if turn.missing_terminal:
            await self.runtime._dispatch(
                self.runtime._emit(
                    RuntimeEventKind.INVOCATION_FAILED,
                    invocation_id=invocation_id,
                    turn_id=turn_id,
                    metadata={"reason": "missing_terminal"},
                )
            )
            raise TransportError("Fake turn returned no terminal event")
        streamed.extend(
            turn.events
            or (
                self.runtime._emit(
                    RuntimeEventKind.OUTPUT_TEXT_DELTA,
                    invocation_id=invocation_id,
                    turn_id=turn_id,
                    payload={"text": chunk},
                )
                for chunk in _chunks(str(turn.value))
            )
        )
        result = RuntimeResult(
            value=turn.value,
            usage=turn.usage,
            runtime=self.runtime._identity,
            model="fake-model",
            profile=self.profile,
            reasoning_effort=self.level,
            turn_id=turn_id,
        )
        streamed.extend(
            self.runtime._terminal_events(invocation_id, None, turn_id, turn.usage, result)
        )
        for event in await self.runtime._publish_events(streamed):
            yield event

    def with_structured_output(
        self, schema: Any, *, policy: StructuredOutputPolicy | None = None
    ) -> _FakeStructuredModel:
        """Return a deterministic host-validated structured facade."""

        if self._tool_snapshot is not None:
            raise CapabilityError("Structured output cannot be combined with host-managed tools")
        return _FakeStructuredModel(self, schema, policy or StructuredOutputPolicy())

    def with_tools(
        self,
        registry: ToolRegistry,
        *,
        executor: ToolExecutor | None = None,
    ) -> FakeRuntimeModel:
        """Return an immutable fake model view with a registry snapshot."""

        spec = self.runtime._profile_spec(self.profile)
        snapshot, bound_executor = self.runtime._tool_binding(spec, registry, executor)
        assert snapshot is not None and bound_executor is not None
        return FakeRuntimeModel(
            self.runtime,
            self.profile,
            self.level,
            snapshot,
            bound_executor,
        )

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return capabilities of the underlying fake runtime."""

        capabilities = await self.runtime.capabilities()
        if self._tool_snapshot is None:
            return RuntimeCapabilities(
                structured_output=capabilities.structured_output,
                ephemeral_sessions=capabilities.ephemeral_sessions,
                persistent_sessions=capabilities.persistent_sessions,
                streaming=capabilities.streaming,
                interruption=capabilities.interruption,
                host_tools=False,
                native_tools=capabilities.native_tools,
                sandbox=capabilities.sandbox,
                usage_reporting=capabilities.usage_reporting,
            )
        return RuntimeCapabilities(
            structured_output=False,
            ephemeral_sessions=capabilities.ephemeral_sessions,
            persistent_sessions=capabilities.persistent_sessions,
            streaming=capabilities.streaming,
            interruption=capabilities.interruption,
            host_tools=bool(self._tool_snapshot.definitions()) and capabilities.host_tools,
            native_tools=False,
            sandbox=capabilities.sandbox,
            usage_reporting=capabilities.usage_reporting,
        )


class _FakeStructuredModel:
    """Provider-free structured model used by deterministic tests."""

    def __init__(self, base: FakeRuntimeModel, schema: Any, policy: StructuredOutputPolicy) -> None:
        """Normalize a Pydantic or Draft 2020-12 schema."""

        self._base = base
        self._policy = policy
        self._model_type: type[BaseModel] | None = None
        self._validator: Draft202012Validator | None = None
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            self._model_type = schema
            self._schema = schema.model_json_schema()
        elif isinstance(schema, dict):
            schema = json.loads(json.dumps(schema))
            try:
                Draft202012Validator.check_schema(schema)
            except (SchemaError, TypeError, ValueError) as exc:
                raise CapabilityError("Invalid Draft 2020-12 structured schema") from exc
            self._schema = schema
            self._validator = Draft202012Validator(schema)
        else:
            raise CapabilityError("Structured schema must be a Pydantic model or JSON object")

    def with_structured_output(
        self, schema: Any, *, policy: StructuredOutputPolicy | None = None
    ) -> _FakeStructuredModel:
        """Return a structured facade with an independent schema and policy."""

        return _FakeStructuredModel(self._base, schema, policy or self._policy)

    def with_tools(self, registry: ToolRegistry, *, executor: ToolExecutor | None = None) -> Any:
        """Reject ambiguous structured-output and dynamic-tool composition."""

        del registry, executor
        raise CapabilityError("Structured output cannot be combined with host-managed tools")

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return capabilities of the fake structured facade."""

        capabilities = await self._base.effective_capabilities()
        if not capabilities.structured_output:
            raise CapabilityError("Structured output is unavailable for this fake runtime")
        return capabilities

    def _validate(self, value: Any) -> Any:
        """Parse and validate one scripted value."""

        import json

        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if self._model_type is not None:
            try:
                return self._model_type.model_validate(parsed)
            except ValidationError as exc:
                raise ValueError("schema validation failed") from exc
        assert self._validator is not None
        errors = list(self._validator.iter_errors(parsed))
        if errors:
            raise ValueError("schema validation failed")
        return parsed

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[Any]:
        """Invoke scripted turns until one validates."""

        terminal: RuntimeResult[Any] | None = None
        async for event in self.astream(input, config=config, include_raw=include_raw):
            if event.kind is RuntimeEventKind.INVOCATION_COMPLETED:
                terminal = event.result
        if terminal is None:
            raise StructuredOutputError("Fake structured invocation returned no result")
        return terminal

    async def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Yield buffered validation and completion events without raw partial JSON."""

        raw_requested = bool(
            include_raw if include_raw is not None else config.include_raw if config else False
        )
        logical_id = self._base.runtime._id_factory()
        yield await self._base.runtime._dispatch(
            self._base.runtime._emit(
                RuntimeEventKind.INVOCATION_STARTED,
                invocation_id=logical_id,
                metadata={
                    **(dict(config.metadata) if config is not None else {}),
                    "max_attempts": self._policy.max_attempts,
                },
            )
        )
        usages: list[RuntimeUsage] = []
        for attempt in range(1, self._policy.max_attempts + 1):
            normalized = RuntimeInput.from_value(input)
            selected_model = config.model if config and config.model else "fake-model"
            result, _generated, _turn = await self._base.runtime._execute(
                normalized,
                model=selected_model,
                profile=self._base.profile,
                level=self._base.level,
                stream=True,
                invocation_metadata=config.metadata if config is not None else None,
            )
            usages.append(result.usage)
            try:
                value = self._validate(result.value)
            except ValueError as exc:
                yield await self._base.runtime._dispatch(
                    self._base.runtime._emit(
                        RuntimeEventKind.VALIDATION_FAILED,
                        invocation_id=logical_id,
                        metadata={"attempt": attempt, "paths": ("$",)},
                    )
                )
                if attempt >= self._policy.max_attempts:
                    error = StructuredOutputError(
                        "Structured output validation attempts exhausted",
                        attempts=attempt,
                        validation_paths=("$",),
                        raw=_sanitize_raw(result.value) if raw_requested else None,
                    )
                    yield await self._base.runtime._dispatch(
                        self._base.runtime._emit(
                            RuntimeEventKind.INVOCATION_FAILED,
                            invocation_id=logical_id,
                            turn_id=result.turn_id,
                            metadata={"attempt": attempt, "reason": "validation_exhausted"},
                        )
                    )
                    raise error from exc
                yield await self._base.runtime._dispatch(
                    self._base.runtime._emit(
                        RuntimeEventKind.RETRY_SCHEDULED,
                        invocation_id=logical_id,
                        metadata={"attempt": attempt, "next_attempt": attempt + 1},
                    )
                )
                continue
            aggregate = RuntimeUsage(
                input_tokens=sum(item.input_tokens or 0 for item in usages),
                output_tokens=sum(item.output_tokens or 0 for item in usages),
                total_tokens=sum(item.total_tokens or 0 for item in usages),
                retry_count=max(0, len(usages) - 1),
            )
            final = RuntimeResult(
                value=value,
                usage=aggregate,
                runtime=result.runtime,
                model=result.model,
                profile=result.profile,
                reasoning_effort=result.reasoning_effort,
                turn_id=result.turn_id,
                raw=result.raw if raw_requested else None,
            )
            yield await self._base.runtime._dispatch(
                self._base.runtime._emit(
                    RuntimeEventKind.INVOCATION_COMPLETED,
                    invocation_id=logical_id,
                    result=final,
                )
            )
            return


class FakeRuntimeSession:
    """Resumable fake session handle."""

    def __init__(self, runtime: FakeRuntime, state: _SessionState) -> None:
        """Bind a handle to retained session state."""

        self._runtime, self._state, self.id = runtime, state, state.descriptor
        self._closed = False
        self._generation = state.generation

    @property
    def descriptor(self) -> str:
        """Decode and return the opaque session descriptor."""

        return self.id

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[Any]:
        """Invoke one turn while enforcing single-active-turn semantics."""

        if self._closed or self._state.deleted or self._generation != self._state.generation:
            raise SessionNotFoundError("Session handle is closed or deleted")
        normalized = RuntimeInput.from_value(input)
        if self._state.context_policy == "runtime" and any(
            message.role != "user" for message in normalized.messages
        ):
            raise ContextPolicyError("Runtime fake sessions accept user messages only")
        if self._state.context_policy == "hybrid" and any(
            message.role not in {"system", "user"} for message in normalized.messages
        ):
            raise ContextPolicyError("Hybrid fake sessions reject assistant/tool replay")
        return (
            await self._runtime._execute(
                normalized,
                model="fake-session",
                profile=self._state.profile,
                level=self._state.level,
                state=self._state,
                invocation_metadata=config.metadata if config is not None else None,
                tool_executor=self._state.tool_executor,
            )
        )[0]

    async def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream one session turn with ordered fake events."""

        if self._closed or self._state.deleted or self._generation != self._state.generation:
            raise SessionNotFoundError("Session handle is closed or deleted")
        normalized = RuntimeInput.from_value(input)
        if self._state.context_policy == "runtime" and any(
            message.role != "user" for message in normalized.messages
        ):
            raise ContextPolicyError("Runtime fake sessions accept user messages only")
        if self._state.context_policy == "hybrid" and any(
            message.role not in {"system", "user"} for message in normalized.messages
        ):
            raise ContextPolicyError("Hybrid fake sessions reject assistant/tool replay")
        active_owned = False
        invocation_id = ""
        try:
            result, generated, turn = await self._runtime._execute(
                normalized,
                model="fake-session",
                profile=self._state.profile,
                level=self._state.level,
                state=self._state,
                keep_active=True,
                stream=True,
                invocation_metadata=config.metadata if config is not None else None,
                tool_executor=self._state.tool_executor,
            )
            active_owned = True
            del result, include_raw
            invocation_id, turn_id = generated[0].invocation_id or "", generated[0].turn_id or ""
            streamed = list(generated)
            streamed.extend(
                turn.events
                or (
                    self._runtime._emit(
                        RuntimeEventKind.OUTPUT_TEXT_DELTA,
                        invocation_id=invocation_id,
                        session_id=self.id,
                        turn_id=turn_id,
                        payload={"text": chunk},
                    )
                    for chunk in _chunks(str(turn.value))
                )
            )
            result = RuntimeResult(
                value=turn.value,
                usage=turn.usage,
                runtime=self._runtime._identity,
                model="fake-session",
                profile=self._state.profile,
                reasoning_effort=self._state.level,
                session_id=self.id,
                turn_id=turn_id,
            )
            streamed.extend(
                self._runtime._terminal_events(invocation_id, self.id, turn_id, turn.usage, result)
            )
            for event in await self._runtime._publish_events(streamed):
                yield event
        except asyncio.CancelledError as exc:
            await self._runtime._dispatch(
                self._runtime._emit(RuntimeEventKind.CANCELLED, session_id=self.id)
            )
            raise CancellationError("Fake turn was cancelled") from exc
        finally:
            if active_owned:
                if self._state.tool_executor is not None and invocation_id:
                    self._state.tool_executor.end_invocation(invocation_id)
                await self._runtime._release(self._state)

    async def interrupt(self) -> None:
        """Request interruption of the active session turn."""

        async with self._state.guard:
            if self._state.active:
                self._state.interrupted = True

    async def close(self) -> None:
        """Close this handle while retaining its resumable state."""

        if not self._closed:
            self._closed = True
            await self._runtime._dispatch(
                self._runtime._emit(RuntimeEventKind.SESSION_CLOSED, session_id=self.id)
            )

    async def archive(self) -> None:
        """Archive this session without deleting retained state."""

        if not self._state.archived:
            self._state.archived = True
            await self._runtime._dispatch(
                self._runtime._emit(RuntimeEventKind.SESSION_ARCHIVED, session_id=self.id)
            )

    async def delete(self) -> None:
        """Delete this session from the fake runtime."""

        if not self._state.deleted:
            self._state.deleted = True
            self._runtime._sessions.pop(self.id, None)
            self._runtime._deleted_sessions.add(self.id)
            self._closed = True
            await self._runtime._dispatch(
                self._runtime._emit(RuntimeEventKind.SESSION_DELETED, session_id=self.id)
            )


class FakeTask(RuntimeTask[Any]):
    """Deterministic in-memory task handle implementing RuntimeTask."""

    def __init__(
        self,
        runtime: FakeRuntime,
        task_id: str,
        *,
        profile: str,
        level: str,
        instructions: str | None,
        config: InvocationConfig,
        tool_snapshot: ToolSnapshot | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Initialize an active fake task.

        Args:
            runtime: Owning FakeRuntime instance.
            task_id: Unique task identifier.
            profile: Execution profile name.
            level: Logical reasoning effort level.
            instructions: Frozen initial instructions.
            config: Default invocation configuration.
            tool_snapshot: Optional frozen tool definitions.
            tool_executor: Optional host tool executor.
        """
        self._runtime = runtime
        self._id = task_id
        self._profile = profile
        self._level = level
        self._model = "fake-model"
        self._instructions = instructions
        self._config = config
        self._tool_snapshot = tool_snapshot
        self._tool_executor = tool_executor
        self._state = TaskState.OPEN
        self._active = False
        self._interrupted = False
        self._active_invocation_id: str | None = None
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._close_event = asyncio.Event()

    @property
    def id(self) -> str:
        """Return the unique task identifier string."""
        return self._id

    @property
    def instructions(self) -> str | None:
        """Return initial task instructions frozen at creation."""
        return self._instructions

    @property
    def state(self) -> TaskState:
        """Return the current lifecycle state of the task."""
        return self._state

    def _ensure_open(self) -> None:
        """Raise SessionNotFoundError if the task is closing or closed."""
        if self._state in (TaskState.CLOSING, TaskState.CLOSED):
            raise SessionNotFoundError(f"Task '{self._id}' not found or already closed")

    def _validate_config(self, config: InvocationConfig | None) -> None:
        """Reject prohibited per-turn configuration overrides.

        Args:
            config: Per-turn invocation config to validate.

        Raises:
            ConfigurationError: If model or reasoning effort modification is attempted.
        """
        if config is None:
            return
        if config.model is not None and config.model != self._model:
            raise ConfigurationError(
                f"Cannot change model from '{self._model}' to '{config.model}' on active task"
            )
        if config.reasoning_effort is not None and config.reasoning_effort != self._level:
            raise ConfigurationError(
                f"Cannot change reasoning effort from '{self._level}' to '{config.reasoning_effort}' on active task"
            )

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[Any]:
        """Execute one turn within the task, reusing the task context.

        Args:
            input: Turn input string or structured RuntimeInput.
            config: Optional per-turn invocation configuration.
            include_raw: Optional override to include raw payloads.

        Returns:
            The terminal RuntimeResult.

        Raises:
            SessionNotFoundError: If the task is closing or already closed.
            SessionBusyError: If another turn is currently running.
            ConfigurationError: If forbidden configuration overrides are passed.
            ContextPolicyError: If replaying non-user messages.
        """
        self._ensure_open()
        if self._lock.locked() or self._active:
            raise SessionBusyError("Task already has an active turn")
        self._validate_config(config)
        validated_input = validate_task_input(input)

        async with self._lock:
            self._active = True
            try:
                result, _, _ = await self._runtime._execute_task_turn(
                    self,
                    validated_input,
                    config=config,
                    include_raw=include_raw,
                    stream=False,
                )
                return result
            finally:
                self._active = False

    async def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream events for one turn within the task.

        Args:
            input: Turn input string or structured RuntimeInput.
            config: Optional per-turn invocation configuration.
            include_raw: Optional override to include raw payloads.

        Yields:
            Correlated runtime lifecycle and output events.

        Raises:
            SessionNotFoundError: If the task is closing or already closed.
            SessionBusyError: If another turn is currently running.
            ConfigurationError: If forbidden configuration overrides are passed.
            ContextPolicyError: If replaying non-user messages.
        """
        self._ensure_open()
        if self._lock.locked() or self._active:
            raise SessionBusyError("Task already has an active turn")
        self._validate_config(config)
        validated_input = validate_task_input(input)

        await self._lock.acquire()
        try:
            self._active = True
            result, generated, turn = await self._runtime._execute_task_turn(
                self,
                validated_input,
                config=config,
                include_raw=include_raw,
                stream=True,
            )
            invocation_id = generated[0].invocation_id or ""
            turn_id = generated[0].turn_id or ""
            streamed = list(generated)
            streamed.extend(
                turn.events
                or (
                    self._runtime._emit(
                        RuntimeEventKind.OUTPUT_TEXT_DELTA,
                        invocation_id=invocation_id,
                        turn_id=turn_id,
                        task_id=self.id,
                        payload={"text": chunk},
                    )
                    for chunk in _chunks(str(turn.value))
                )
            )
            res = RuntimeResult(
                value=turn.value,
                usage=turn.usage,
                runtime=self._runtime._identity,
                model=self._model,
                profile=self._profile,
                reasoning_effort=self._level,
                turn_id=turn_id,
                task_id=self.id,
            )
            streamed.extend(
                self._runtime._terminal_events(
                    invocation_id, None, turn_id, turn.usage, res, task_id=self.id
                )
            )
            for event in await self._runtime._publish_events(streamed):
                yield event
        finally:
            self._active = False
            self._lock.release()

    async def interrupt(self) -> None:
        """Interrupt any active turn on this task.

        Raises:
            SessionNotFoundError: If the task is closing or closed.
        """
        self._ensure_open()
        if self._active:
            self._interrupted = True

    async def close(self) -> None:
        """Idempotently close this task and clean up resources."""
        async with self._close_lock:
            if self._state == TaskState.CLOSED:
                return
            if self._state == TaskState.CLOSING:
                await self._close_event.wait()
                return
            self._state = TaskState.CLOSING

        try:
            if self._active and self._active_invocation_id and self._tool_executor is not None:
                self._tool_executor.end_invocation(self._active_invocation_id)
            self._runtime._tasks.pop(self._id, None)
        finally:
            self._state = TaskState.CLOSED
            self._close_event.set()
            await self._runtime._dispatch(
                self._runtime._emit(RuntimeEventKind.TASK_CLOSED, task_id=self._id)
            )

    async def __aenter__(self) -> FakeTask:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Close the task upon leaving the context manager."""
        del exc_type, exc_val, exc_tb
        await self.close()


def _chunks(value: str, size: int = 8) -> tuple[str, ...]:
    """Split text into deterministic output chunks."""

    return tuple(value[index : index + size] for index in range(0, len(value), size))


def _sanitize_raw(value: Any) -> str:
    """Redact credential-shaped values before exposing invalid raw output."""

    text = str(value)
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, Mapping):
        return json.dumps(_redact_json(parsed), ensure_ascii=False, sort_keys=True)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", text)
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^,}\s]+",
        r"\1=[REDACTED]",
        text,
    )


def _redact_json(value: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact credential-shaped JSON keys."""

    secret_keys = {"api_key", "apikey", "token", "secret", "password", "authorization"}
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).casefold().replace("-", "_")
        if normalized in secret_keys:
            result[str(key)] = "[REDACTED]"
        elif isinstance(item, Mapping):
            result[str(key)] = _redact_json(item)
        elif isinstance(item, list):
            result[str(key)] = [
                _redact_json(entry) if isinstance(entry, Mapping) else entry for entry in item
            ]
        else:
            result[str(key)] = item
    return result
