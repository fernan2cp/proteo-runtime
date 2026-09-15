"""Public Codex runtime implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.errors import (
    AgentRuntimeError,
    AuthenticationError,
    CancellationError,
    CapabilityError,
    ContextPolicyError,
    InterruptedError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
    SessionBusyError,
    SessionMismatchError,
    SessionNotFoundError,
    TransportError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.input import RuntimeInput
from proteo_runtime.core.model import InvocationConfig, RuntimeModel, RuntimeResult
from proteo_runtime.core.profiles import profile_spec
from proteo_runtime.core.session_codec import SessionCodec

from ._compat import delete_thread
from ._mapping import account_value, fingerprint, identity_metadata, serialize_input
from ._runner import TurnRun
from ._workspace import create_workspace, remove_workspace


def _create_sdk() -> Any:
    """Construct the pinned asynchronous Codex SDK client."""

    from openai_codex import AsyncCodex

    return AsyncCodex()


def _enum(name: str, member: str) -> Any:
    """Load one SDK enum member lazily."""

    from openai_codex import ApprovalMode, Sandbox

    return getattr(ApprovalMode if name == "ApprovalMode" else Sandbox, member)


def _effort_value(value: object) -> str:
    """Extract a reasoning effort from an SDK option or enum."""

    option = getattr(value, "reasoning_effort", value)
    return str(getattr(option, "value", option))


def _safe_model_id(model: object) -> str:
    """Return a model identifier from a real object or a test double."""

    return str(getattr(model, "model", getattr(model, "id", "")))


def _map_sdk_error(exc: Exception, operation: str) -> AgentRuntimeError:
    """Map an SDK failure to a stable Proteo error without exposing payloads."""

    if isinstance(exc, AgentRuntimeError):
        return exc
    name = type(exc).__name__.lower()
    message = f"Codex {operation} failed"
    if "auth" in name or "login" in name or "credential" in name:
        return AuthenticationError(message)
    if "timeout" in name:
        return RuntimeTimeoutError(message)
    if "cancel" in name:
        return CancellationError(message)
    if "notfound" in name or "not_found" in name:
        return SessionNotFoundError(message)
    if "interrupt" in name:
        return InterruptedError(message)
    if "capab" in name or "unsupported" in name:
        return CapabilityError(message)
    return TransportError(message, details={"exception_type": type(exc).__name__})


@dataclass
class _SessionState:
    """Mutable provider state shared by all handles for one persistent thread."""

    runtime: CodexRuntime
    thread: Any
    descriptor: str
    model: str
    effort: str
    profile: str
    workspace: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: TurnRun | None = None
    closed_handles: int = 0
    archived: bool = False
    deleted: bool = False


class CodexRuntime:
    """Proteo runtime backed by the managed ChatGPT Codex SDK."""

    def __init__(self, default_model: str | None = None) -> None:
        """Initialize a lazy runtime without reading authentication."""

        self.default_model = default_model
        self._sdk: Any | None = None
        self._identity: RuntimeIdentity | None = None
        self._identity_fingerprint: str | None = None
        self._identity_metadata: Mapping[str, Any] = {}
        self._catalog: dict[str, Any] = {}
        self._selected_model: str | None = None
        self._started = False
        self._closed = False
        self._sessions: dict[str, _SessionState] = {}
        self._active_runs: dict[str, TurnRun] = {}
        self._sequence = 0
        self.events: list[RuntimeEvent] = []

    @property
    def identity(self) -> RuntimeIdentity:
        """Return the sanitized runtime identity after startup."""

        if self._identity is None:
            raise RuntimeUnavailableError("CodexRuntime.start() must be called first")
        return self._identity

    async def start(self) -> None:
        """Start the SDK and validate managed ChatGPT authentication."""

        if self._started and not self._closed:
            return
        sdk = _create_sdk()
        try:
            response = await sdk.account(refresh_token=False)
            fingerprint_value, metadata = identity_metadata(response)
            account_value(response)
            models_response = await sdk.models(include_hidden=False)
            models = getattr(models_response, "data", models_response)
            catalog = {
                _safe_model_id(model): model
                for model in models
                if not bool(getattr(model, "hidden", False))
            }
            selected = self._select_default(catalog)
        except AgentRuntimeError:
            await self._close_sdk(sdk)
            raise
        except Exception as exc:
            await self._close_sdk(sdk)
            raise _map_sdk_error(exc, "startup") from exc
        self._sdk = sdk
        self._identity_fingerprint = fingerprint_value
        self._identity_metadata = metadata
        self._identity = RuntimeIdentity("codex", fingerprint_value, "Codex", metadata)
        self._catalog = catalog
        self._selected_model = selected
        self._started = True
        self._closed = False
        self._emit(RuntimeEventKind.RUNTIME_STARTED)

    def _select_default(self, catalog: Mapping[str, Any]) -> str:
        """Resolve an explicit model or the unique catalog default."""

        if self.default_model is not None:
            if self.default_model not in catalog:
                raise CapabilityError(f"Unknown Codex model: {self.default_model}")
            return self.default_model
        defaults = [
            name for name, model in catalog.items() if bool(getattr(model, "is_default", False))
        ]
        if len(defaults) != 1:
            raise CapabilityError("Codex catalog must expose one default model")
        return defaults[0]

    async def _close_sdk(self, sdk: Any) -> None:
        """Close an SDK object if it exposes the stable close operation."""

        close = getattr(sdk, "close", None)
        if close is not None:
            await close()

    async def close(self) -> None:
        """Close the SDK and interrupt active work idempotently."""

        if self._closed and self._sdk is None:
            return
        active = list(self._active_runs.values())
        for run in active:
            try:
                await asyncio.wait_for(run.interrupt(), timeout=5.0)
            except Exception:
                self._closed = True
        if self._sdk is not None:
            await self._close_sdk(self._sdk)
        for state in self._sessions.values():
            remove_workspace(state.workspace)
        self._active_runs.clear()
        self._sdk = None
        was_started = self._started
        self._started = False
        self._closed = True
        if was_started:
            self._emit(RuntimeEventKind.RUNTIME_STOPPED)

    async def __aenter__(self) -> CodexRuntime:
        """Start the runtime for an async context manager."""

        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Close the runtime at the end of an async context manager."""

        del exc_type, exc, traceback
        await self.close()

    def _require_started(self) -> Any:
        """Return the active SDK or raise without implicit startup."""

        if not self._started or self._closed or self._sdk is None:
            raise RuntimeUnavailableError("CodexRuntime.start() must be called first")
        return self._sdk

    async def capabilities(self) -> RuntimeCapabilities:
        """Return the provider capabilities available in Phase 1."""

        return RuntimeCapabilities(
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

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return the runtime capabilities with profile restrictions applied."""

        return await self.capabilities()

    async def models(self) -> list[Any]:
        """Return the visible Codex model catalog without SDK objects."""

        self._require_started()
        from proteo_runtime.core.model_info import ModelInfo

        capabilities = await self.capabilities()
        return [
            ModelInfo(
                identifier=name,
                display_name=str(getattr(model, "display_name", name)),
                supported_reasoning_efforts=tuple(
                    _effort_value(value)
                    for value in (getattr(model, "supported_reasoning_efforts", ()) or ())
                ),
                capabilities=capabilities,
                is_default=bool(getattr(model, "is_default", False)),
                description=getattr(model, "description", None),
            )
            for name, model in self._catalog.items()
        ]

    def model(self, *, profile: str, level: str = "medium") -> RuntimeModel[str]:
        """Create a model view for a provider-neutral profile."""

        profile_spec(profile)
        return _CodexModel(self, profile, InvocationConfig(reasoning_effort=level))

    async def brain(self, config: InvocationConfig | None = None) -> RuntimeModel[str]:
        """Return the ephemeral brain model after checking lifecycle."""

        self._require_started()
        return _CodexModel(self, "brain", config or InvocationConfig())

    async def session(
        self, profile: str = "session", config: InvocationConfig | None = None
    ) -> _CodexSession:
        """Create a persistent Codex session with an opaque descriptor."""

        self._require_started()
        spec = profile_spec(profile)
        if not spec.persistent:
            raise CapabilityError("Codex persistent sessions require the session profile")
        model = self._resolve_model(config)
        effort = self._resolve_effort(config, model)
        workspace = create_workspace()
        try:
            thread = await self._require_started().thread_start(
                ephemeral=False,
                model=model,
                cwd=str(workspace),
                approval_mode=_enum("ApprovalMode", "deny_all"),
                sandbox=_enum("Sandbox", "read_only"),
            )
            descriptor = self._make_descriptor(
                model,
                effort,
                profile,
                spec.context.value,
                spec.security_policy,
                str(getattr(thread, "id", "")),
            )
            state = _SessionState(self, thread, descriptor, model, effort, profile, workspace)
            self._sessions[descriptor] = state
            self._emit(RuntimeEventKind.SESSION_CREATED, session_id=descriptor)
            return _CodexSession(state)
        except Exception as exc:
            remove_workspace(workspace)
            raise _map_sdk_error(exc, "session creation") from exc

    def _make_descriptor(
        self,
        model: str,
        effort: str,
        profile: str,
        context_policy: str,
        security_policy: str,
        provider_id: str,
    ) -> str:
        """Encode the canonical Phase 1 session descriptor."""

        return SessionCodec.encode(
            provider="codex",
            provider_session_id=provider_id,
            identity_fingerprint=self._identity_fingerprint or "",
            configuration_fingerprint=self._configuration_fingerprint(
                model, effort, profile, context_policy, security_policy
            ),
            profile=profile,
            level=effort,
            context_policy=context_policy,
            security_policy=security_policy,
        )

    def _configuration_fingerprint(
        self, model: str, effort: str, profile: str, context_policy: str, security_policy: str
    ) -> str:
        """Hash all frozen session configuration and permission policy."""

        return fingerprint(
            {
                "provider": "codex",
                "sdk": "openai-codex-0.147",
                "model": model,
                "effort": effort,
                "profile": profile,
                "context_policy": context_policy,
                "security_policy": security_policy,
                "sandbox": "read_only",
                "approval": "deny_all",
            }
        )

    async def resume_session(self, descriptor: str | object) -> _CodexSession:
        """Validate and resume a persistent session descriptor."""

        sdk = self._require_started()
        raw = descriptor if isinstance(descriptor, str) else str(descriptor)
        decoded = SessionCodec.decode(raw)
        if (
            decoded.provider != "codex"
            or decoded.identity_fingerprint != self._identity_fingerprint
        ):
            raise SessionMismatchError("Session identity does not match the runtime")
        profile_spec(decoded.profile)
        model = self._selected_model or ""
        expected = self._configuration_fingerprint(
            model, decoded.level, decoded.profile, decoded.context_policy, decoded.security_policy
        )
        if decoded.configuration_fingerprint != expected:
            raise SessionMismatchError("Session configuration does not match the runtime")
        existing = self._sessions.get(raw)
        workspace = create_workspace()
        try:
            thread = await sdk.thread_resume(
                decoded.provider_session_id,
                model=model,
                cwd=str(workspace),
                approval_mode=_enum("ApprovalMode", "deny_all"),
                sandbox=_enum("Sandbox", "read_only"),
            )
        except Exception as exc:
            remove_workspace(workspace)
            raise SessionNotFoundError("Codex session was not found") from exc
        if existing is not None and not existing.deleted:
            existing.thread = thread
            existing.workspace = workspace
            existing.closed_handles = 0
            state = existing
        else:
            state = _SessionState(
                self, thread, raw, model, decoded.level, decoded.profile, workspace
            )
            self._sessions[raw] = state
        self._emit(RuntimeEventKind.SESSION_RESUMED, session_id=raw)
        return _CodexSession(state)

    async def migrate_session(
        self, session_id: str, *, profile: str, level: str = "medium", security_policy: str
    ) -> _CodexSession:
        """Reject migration until Phase 2 without contacting the provider."""

        del session_id, profile, level, security_policy
        raise CapabilityError("Session migration is reserved for Phase 2")

    def _resolve_model(self, config: InvocationConfig | None) -> str:
        """Resolve and validate a configured model."""

        selected = config.model if config is not None and config.model else self._selected_model
        if selected not in self._catalog:
            raise CapabilityError(f"Unknown Codex model: {selected}")
        return str(selected)

    def _resolve_effort(self, config: InvocationConfig | None, model: str) -> str:
        """Resolve and validate reasoning effort against the catalog."""

        configured = config.reasoning_effort if config is not None else None
        supported = {
            _effort_value(value)
            for value in (getattr(self._catalog[model], "supported_reasoning_efforts", ()) or ())
        }
        if configured is None:
            default = getattr(self._catalog[model], "default_reasoning_effort", None)
            effort = str(getattr(default, "value", default or "medium"))
        else:
            effort = str(getattr(configured, "value", configured))
        if supported and effort not in supported:
            raise CapabilityError(f"Unsupported reasoning effort: {effort}")
        return effort

    def _register_run(self, run: TurnRun) -> None:
        """Register one active turn for coordinated cleanup."""

        self._active_runs[run.invocation_id] = run

    def _unregister_run(self, run: TurnRun) -> None:
        """Remove one completed turn from the active registry."""

        self._active_runs.pop(run.invocation_id, None)

    def _emit(self, kind: RuntimeEventKind, *, session_id: str | None = None) -> None:
        """Record a provider-neutral lifecycle event."""

        identity = self._identity or RuntimeIdentity("codex", "uninitialized")
        event = RuntimeEvent(
            kind=kind,
            event_id=f"runtime:{self._sequence}",
            sequence=self._sequence,
            occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            runtime=identity,
            session_id=session_id,
        )
        self._sequence += 1
        self.events.append(event)


class _CodexModel:
    """Internal model implementation shared by brain and session factories."""

    def __init__(self, runtime: CodexRuntime, profile: str, config: InvocationConfig) -> None:
        """Store model configuration without contacting Codex."""

        self.runtime = runtime
        self.profile = profile
        self.config = config

    def with_structured_output(self, schema: Any) -> RuntimeModel[Any]:
        """Reject structured output before any provider access."""

        del schema
        raise CapabilityError("Structured output is reserved for Phase 2")

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return effective capabilities for this model profile."""

        capabilities = await self.runtime.capabilities()
        if self.profile in {"structured", "controlled_agent", "native"}:
            return RuntimeCapabilities(
                structured_output=False,
                ephemeral_sessions=capabilities.ephemeral_sessions,
                persistent_sessions=capabilities.persistent_sessions,
                streaming=capabilities.streaming,
                interruption=capabilities.interruption,
                host_tools=False,
                native_tools=False,
                sandbox=capabilities.sandbox,
                usage_reporting=capabilities.usage_reporting,
            )
        return capabilities

    async def _start_run(
        self, value: str | RuntimeInput, include_raw: bool
    ) -> tuple[TurnRun, Path]:
        """Create an ephemeral thread and start one async turn."""

        sdk = self.runtime._require_started()
        prompt, instructions = serialize_input(value)
        model = self.runtime._resolve_model(self.config)
        effort = self.runtime._resolve_effort(self.config, model)
        workspace = create_workspace()
        try:
            thread = await sdk.thread_start(
                ephemeral=True,
                model=model,
                developer_instructions=instructions,
                cwd=str(workspace),
                approval_mode=_enum("ApprovalMode", "deny_all"),
                sandbox=_enum("Sandbox", "read_only"),
            )
            handle = await thread.turn(
                prompt,
                model=model,
                effort=effort,
                approval_mode=_enum("ApprovalMode", "deny_all"),
                sandbox=_enum("Sandbox", "read_only"),
            )
        except Exception as exc:
            remove_workspace(workspace)
            raise _map_sdk_error(exc, "brain invocation") from exc
        run = TurnRun(
            runtime_name="codex",
            identity=self.runtime.identity,
            handle=handle,
            invocation_id=uuid4().hex,
            model=model,
            profile=self.profile,
            effort=effort,
            include_raw=include_raw,
        )
        self.runtime._register_run(run)
        return run, workspace

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[str]:
        """Invoke one ephemeral Codex turn and collect its result."""

        effective_config = config or self.config
        effective_raw = self.config.include_raw if include_raw is None else include_raw
        original = self.config
        self.config = effective_config
        run, workspace = await self._start_run(input, effective_raw)
        try:
            timeout = effective_config.timeout_seconds
            if timeout is None:
                async for _ in run.events():
                    pass
            else:
                async with asyncio.timeout(timeout):
                    async for _ in run.events():
                        pass
            if run.result is None:
                raise TransportError("Codex returned no terminal result")
            return run.result
        except TimeoutError as exc:
            await self._interrupt_or_invalidate(run)
            raise RuntimeTimeoutError("Codex turn timed out") from exc
        except asyncio.CancelledError as exc:
            await self._interrupt_or_invalidate(run)
            raise CancellationError("Codex turn was cancelled") from exc
        except Exception as exc:
            if isinstance(exc, AgentRuntimeError):
                raise
            raise _map_sdk_error(exc, "brain invocation") from exc
        finally:
            self.config = original
            self.runtime._unregister_run(run)
            remove_workspace(workspace)

    async def _interrupt_or_invalidate(self, run: TurnRun) -> None:
        """Interrupt a turn and invalidate transport when it does not confirm."""

        try:
            await asyncio.wait_for(run.interrupt(), timeout=5.0)
        except Exception:
            await self.runtime.close()

    async def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream one ephemeral Codex turn through the shared runner."""

        effective_config = config or self.config
        effective_raw = self.config.include_raw if include_raw is None else include_raw
        original = self.config
        self.config = effective_config
        run, workspace = await self._start_run(input, effective_raw)
        try:
            timeout = effective_config.timeout_seconds
            if timeout is None:
                async for event in run.events():
                    yield event
            else:
                async with asyncio.timeout(timeout):
                    async for event in run.events():
                        yield event
        except TimeoutError as exc:
            await self._interrupt_or_invalidate(run)
            raise RuntimeTimeoutError("Codex stream timed out") from exc
        except asyncio.CancelledError as exc:
            await self._interrupt_or_invalidate(run)
            raise CancellationError("Codex stream was cancelled") from exc
        except Exception as exc:
            if isinstance(exc, AgentRuntimeError):
                raise
            raise _map_sdk_error(exc, "brain streaming") from exc
        finally:
            self.config = original
            self.runtime._unregister_run(run)
            remove_workspace(workspace)


class _CodexSession:
    """Internal persistent session handle."""

    def __init__(self, state: _SessionState) -> None:
        """Bind a public handle to shared persistent state."""

        self._state = state
        self._closed = False

    @property
    def id(self) -> str:
        """Return the opaque descriptor identifier."""

        return self._state.descriptor

    @property
    def descriptor(self) -> str:
        """Return the opaque descriptor."""

        return self._state.descriptor

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[str]:
        """Run one user-only persistent turn with fail-fast concurrency."""

        self._ensure_open()
        runtime_input = RuntimeInput.from_value(input)
        self._validate_user_input(runtime_input)
        if self._state.lock.locked():
            raise SessionBusyError("Session already has an active turn")
        async with self._state.lock:
            prompt, _ = serialize_input(runtime_input)
            run = await self._start_turn(prompt, config, include_raw)
            try:
                timeout = (config or InvocationConfig()).timeout_seconds
                if timeout is None:
                    async for _ in run.events():
                        pass
                else:
                    async with asyncio.timeout(timeout):
                        async for _ in run.events():
                            pass
                if run.result is None:
                    raise TransportError("Codex returned no terminal result")
                return run.result
            except TimeoutError as exc:
                await self._interrupt_or_invalidate(run)
                raise RuntimeTimeoutError("Codex session turn timed out") from exc
            finally:
                self._state.active = None
                self._state.runtime._unregister_run(run)

    async def _start_turn(
        self, prompt: str, config: InvocationConfig | None, include_raw: bool | None
    ) -> TurnRun:
        """Start one turn on the shared persistent thread."""

        del config
        handle = await self._state.thread.turn(
            prompt,
            model=self._state.model,
            effort=self._state.effort,
            approval_mode=_enum("ApprovalMode", "deny_all"),
            sandbox=_enum("Sandbox", "read_only"),
        )
        run = TurnRun(
            runtime_name="codex",
            identity=self._state.runtime.identity,
            handle=handle,
            invocation_id=uuid4().hex,
            model=self._state.model,
            profile=self._state.profile,
            effort=self._state.effort,
            session_id=self.id,
            include_raw=bool(include_raw),
        )
        self._state.active = run
        self._state.runtime._register_run(run)
        return run

    async def astream(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream one persistent user-only turn with the shared lock."""

        self._ensure_open()
        runtime_input = RuntimeInput.from_value(input)
        self._validate_user_input(runtime_input)
        if self._state.lock.locked():
            raise SessionBusyError("Session already has an active turn")
        await self._state.lock.acquire()
        run: TurnRun | None = None
        try:
            prompt, _ = serialize_input(runtime_input)
            run = await self._start_turn(prompt, config, include_raw)
            timeout = (config or InvocationConfig()).timeout_seconds
            if timeout is None:
                async for event in run.events():
                    yield event
            else:
                async with asyncio.timeout(timeout):
                    async for event in run.events():
                        yield event
        except TimeoutError as exc:
            if run is not None:
                await self._interrupt_or_invalidate(run)
            raise RuntimeTimeoutError("Codex session stream timed out") from exc
        except asyncio.CancelledError as exc:
            if run is not None:
                await self._interrupt_or_invalidate(run)
            raise CancellationError("Codex session stream was cancelled") from exc
        finally:
            if run is not None:
                self._state.runtime._unregister_run(run)
            self._state.active = None
            self._state.lock.release()

    def _validate_user_input(self, value: RuntimeInput) -> None:
        """Reject system, assistant, and tool replay in persistent sessions."""

        if any(message.role != "user" for message in value.messages):
            raise ContextPolicyError("Persistent Codex sessions accept user messages only")

    def _ensure_open(self) -> None:
        """Reject operations after local close or provider deletion."""

        if self._closed or self._state.deleted:
            raise SessionNotFoundError("Codex session handle is closed or deleted")

    async def _interrupt_or_invalidate(self, run: TurnRun) -> None:
        """Interrupt a session turn and close the runtime when needed."""

        try:
            await asyncio.wait_for(run.interrupt(), timeout=5.0)
        except Exception:
            await self._state.runtime.close()

    async def interrupt(self) -> None:
        """Interrupt the active persistent turn, if present."""

        if self._state.active is not None:
            await self._state.active.interrupt()

    async def close(self) -> None:
        """Close this local handle while preserving provider history."""

        if not self._closed:
            if self._state.active is not None:
                await self._state.active.interrupt()
            self._closed = True
            self._state.closed_handles += 1
            remove_workspace(self._state.workspace)
            self._state.runtime._emit(RuntimeEventKind.SESSION_CLOSED, session_id=self.id)

    async def archive(self) -> None:
        """Archive the provider thread through the stable API."""

        self._ensure_open()
        if not self._state.archived:
            try:
                sdk = self._state.runtime._require_started()
                await sdk.thread_archive(str(getattr(self._state.thread, "id", "")))
            except Exception as exc:
                raise _map_sdk_error(exc, "session archive") from exc
            self._state.archived = True
            self._state.runtime._emit(RuntimeEventKind.SESSION_ARCHIVED, session_id=self.id)

    async def delete(self) -> None:
        """Delete the provider thread through the isolated compatibility shim."""

        self._ensure_open()
        if not self._state.deleted:
            try:
                await delete_thread(
                    self._state.runtime._require_started(),
                    str(getattr(self._state.thread, "id", "")),
                )
            except Exception as exc:
                if isinstance(exc, AgentRuntimeError):
                    raise
                raise _map_sdk_error(exc, "session deletion") from exc
            self._state.deleted = True
            self._closed = True
            remove_workspace(self._state.workspace)
            self._state.runtime._emit(RuntimeEventKind.SESSION_DELETED, session_id=self.id)
