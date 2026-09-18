"""Public Codex runtime implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from proteo_runtime.config import RuntimeConfigV1, load_runtime_config
from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.diagnostics import DiagnosticSeverity, RuntimeDiagnostic
from proteo_runtime.core.errors import (
    AgentRuntimeError,
    AuthenticationError,
    CancellationError,
    CapabilityError,
    ConfigurationError,
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
from proteo_runtime.core.model import (
    InvocationConfig,
    RuntimeModel,
    RuntimeResult,
    StructuredOutputPolicy,
)
from proteo_runtime.core.observability import ObservabilityStatus
from proteo_runtime.core.profiles import (
    profile_spec,
    validate_model_profile,
    validate_session_profile,
    validate_task_profile,
)
from proteo_runtime.core.session_codec import SessionCodec
from proteo_runtime.core.task import RuntimeTask, TaskState, validate_task_input
from proteo_runtime.observability import ObservabilityConfig, RuntimeEventBus
from proteo_runtime.tools import ToolExecutor, ToolRegistry, ToolSnapshot

from ._compat import delete_thread
from ._mapping import account_value, fingerprint, identity_metadata, serialize_input
from ._runner import TurnRun
from ._workspace import create_workspace, remove_workspace
from .experimental import (
    CodexToolBridge,
    CodexToolMux,
    install_bridge,
    probe_dynamic_tools,
    resume_thread,
    start_thread,
)
from .native_otel import CodexNativeOtelConfig, native_otel_capabilities


def _create_sdk(native_otel: Any | None = None, *, experimental_dynamic_tools: bool = False) -> Any:
    """Construct the pinned asynchronous Codex SDK client."""

    from openai_codex import AsyncCodex

    if native_otel is None and not experimental_dynamic_tools:
        # Keep the SDK's experimental surface disabled unless the caller opts in.
        # Older test doubles may only accept the no-argument constructor, so retain
        # a narrow compatibility fallback for them.
        from openai_codex import CodexConfig

        try:
            return AsyncCodex(config=CodexConfig(experimental_api=False))
        except TypeError:
            return AsyncCodex()
    from openai_codex import CodexConfig

    capabilities = native_otel_capabilities(native_otel) if native_otel is not None else None
    if capabilities is not None and not capabilities.supported:
        raise ConfigurationError("Codex-native OpenTelemetry is unsupported by this SDK")
    overrides = native_otel.overrides() if native_otel is not None else ()
    return AsyncCodex(
        config=CodexConfig(
            config_overrides=overrides,
            experimental_api=experimental_dynamic_tools,
        )
    )


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
    text = str(exc).casefold()
    message = f"Codex {operation} failed"
    if "auth" in name or "login" in name or "credential" in name:
        return AuthenticationError(message)
    if "timeout" in name:
        return RuntimeTimeoutError(message)
    if "cancel" in name:
        return CancellationError(message)
    if (
        "notfound" in name
        or "not_found" in name
        or "lookup" in name
        or "no rollout" in text
        or "not found" in text
    ):
        return SessionNotFoundError(message)
    if "interrupt" in name:
        return InterruptedError(message)
    if "capab" in name or "unsupported" in name:
        return CapabilityError(message)
    return TransportError(message, details={"exception_type": type(exc).__name__})


def _merge_invocation_config(
    base: InvocationConfig, override: InvocationConfig | None
) -> InvocationConfig:
    """Merge an optional invocation override without mutating the bound model."""

    if override is None:
        return base
    metadata = dict(base.metadata)
    metadata.update(override.metadata)
    return InvocationConfig(
        model=override.model if override.model is not None else base.model,
        reasoning_effort=(
            override.reasoning_effort
            if override.reasoning_effort is not None
            else base.reasoning_effort
        ),
        include_raw=(
            override.include_raw if override.include_raw is not None else base.include_raw
        ),
        timeout_seconds=(
            override.timeout_seconds
            if override.timeout_seconds is not None
            else base.timeout_seconds
        ),
        metadata=metadata,
    )


@dataclass
class _SessionState:
    """Mutable provider state shared by all handles for one persistent thread."""

    runtime: CodexRuntime
    thread: Any
    descriptor: str
    model: str
    effort: str
    profile: str
    level: str
    context_policy: str
    security_policy: str
    workspace: Path
    config: InvocationConfig = field(default_factory=InvocationConfig)
    tool_snapshot: ToolSnapshot | None = None
    tool_executor: ToolExecutor | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: TurnRun | None = None
    closed_handles: int = 0
    archived: bool = False
    deleted: bool = False
    generation: int = 0


@dataclass(frozen=True)
class _ResolvedBinding:
    """Immutable profile resolution used by one model or session handle."""

    profile: str
    level: str
    model: str
    effort: str
    spec: Any


class CodexRuntime:
    """Proteo runtime backed by the managed ChatGPT Codex SDK."""

    def __init__(
        self,
        default_model: str | None = None,
        *,
        config_path: str | Path | None = None,
        config: RuntimeConfigV1 | None = None,
        observability: ObservabilityConfig | None = None,
        codex_native_otel: CodexNativeOtelConfig | None = None,
        experimental_dynamic_tools: bool = False,
    ) -> None:
        """Initialize a lazy runtime without reading authentication."""

        self.default_model = default_model
        self._config = load_runtime_config(config_path=config_path, config=config)
        self._observability = RuntimeEventBus(observability)
        self._codex_native_otel = codex_native_otel
        self.experimental_dynamic_tools = experimental_dynamic_tools
        self._dynamic_tools_compatibility = probe_dynamic_tools()
        self._sdk: Any | None = None
        self._identity: RuntimeIdentity | None = None
        self._identity_fingerprint: str | None = None
        self._identity_metadata: Mapping[str, Any] = {}
        self._catalog: dict[str, Any] = {}
        self._selected_model: str | None = None
        self._started = False
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._sessions: dict[str, _SessionState] = {}
        self._tasks: dict[str, RuntimeTask[Any]] = {}
        self._active_runs: dict[str, TurnRun] = {}
        self._sequence = 0
        self.events: list[RuntimeEvent] = []
        self._diagnostics: list[RuntimeDiagnostic] = []

    @property
    def diagnostics(self) -> tuple[RuntimeDiagnostic, ...]:
        """Return a snapshot of runtime diagnostics recorded during operations."""
        return tuple(self._diagnostics)

    def _record_diagnostic(self, diagnostic: RuntimeDiagnostic) -> None:
        """Record one runtime diagnostic on the runtime and the event bus.

        Args:
            diagnostic: The runtime diagnostic to record.
        """
        self._diagnostics.append(diagnostic)
        self._observability.record_diagnostic(diagnostic)

    def observability_status(self) -> ObservabilityStatus:
        """Return the aggregate health of configured observers."""

        return self._observability.status

    def codex_native_otel_capabilities(self) -> Any:
        """Report native Codex telemetry support without starting inference."""

        return native_otel_capabilities(self._codex_native_otel)

    @property
    def name(self) -> str:
        """Return the runtime provider name."""

        return "codex"

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
        sdk = (
            _create_sdk(
                self._codex_native_otel,
                experimental_dynamic_tools=self.experimental_dynamic_tools,
            )
            if self.experimental_dynamic_tools or self._codex_native_otel is not None
            else _create_sdk()
        )
        try:
            if self._config.runtime != "codex":
                raise ConfigurationError(
                    "Runtime configuration does not target Codex", path="runtime"
                )
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
            self._validate_configured_catalog(catalog)
            selected = self._select_default(catalog) if self.default_model is not None else None
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
        try:
            await self._dispatch(self._emit(RuntimeEventKind.RUNTIME_STARTED))
        except AgentRuntimeError:
            with suppress(AgentRuntimeError):
                await self.close()
            raise

    def _select_default(self, catalog: Mapping[str, Any]) -> str:
        """Resolve an explicitly requested model or a legacy catalog default."""

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

    def _validate_configured_catalog(self, catalog: Mapping[str, Any]) -> None:
        """Validate every configured model and effort against one startup catalog."""

        for profile, levels in self._config.profiles.items():
            for level, mapping in levels.items():
                model = mapping.model
                effort = mapping.reasoning_effort
                if model not in catalog:
                    raise CapabilityError(
                        f"Unknown Codex model at profiles.{profile}.{level}: {model}"
                    )
                supported = {
                    _effort_value(value)
                    for value in (getattr(catalog[model], "supported_reasoning_efforts", ()) or ())
                }
                if supported and effort not in supported:
                    raise CapabilityError(
                        f"Unsupported reasoning effort at profiles.{profile}.{level}: {effort}"
                    )

    async def _close_sdk(self, sdk: Any) -> None:
        """Close an SDK object if it exposes the stable close operation."""

        close = getattr(sdk, "close", None)
        if close is not None:
            await close()

    async def close(self) -> None:
        """Close the SDK and interrupt active work idempotently in dependency order."""

        async with self._close_lock:
            if self._closed and self._sdk is None:
                return
            self._closed = True

            # 1. Close active tasks while SDK and mux are still available for thread deletion and cleanup
            tasks = list(self._tasks.values())
            for task in tasks:
                with suppress(Exception):
                    await task.close()
            self._tasks.clear()

            # 2. Interrupt and await non-task active runs
            active = list(self._active_runs.values())
            for run in active:
                try:
                    await asyncio.wait_for(run.interrupt(), timeout=5.0)
                    await asyncio.wait_for(run.wait_finished(), timeout=5.0)
                except Exception:
                    # A transport that cannot confirm interruption is never reused.
                    self._active_runs.pop(run.invocation_id, None)
            self._active_runs.clear()

            # 3. Clean up persistent session active runs and local workspaces
            for state in list(self._sessions.values()):
                with suppress(Exception):
                    if state.active is not None:
                        await state.active.interrupt()
                        with suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(state.active.wait_finished(), timeout=5.0)
                    remove_workspace(state.workspace)
            self._sessions.clear()

            # 4. Clean tool mux routes
            if self._sdk is not None:
                sync_client = getattr(getattr(self._sdk, "_client", None), "_sync", None)
                mux = getattr(sync_client, "_approval_handler", None)
                if isinstance(mux, CodexToolMux):
                    mux.close()

            # 5. Close SDK transport
            if self._sdk is not None:
                await self._close_sdk(self._sdk)
                self._sdk = None

            # 6. Reset runtime catalog and active flags
            self._catalog.clear()
            was_started = self._started
            self._started = False

            # 7. Dispatch RUNTIME_STOPPED
            observability_error: AgentRuntimeError | None = None
            if was_started:
                try:
                    await self._dispatch(self._emit(RuntimeEventKind.RUNTIME_STOPPED))
                except AgentRuntimeError as exc:
                    observability_error = exc

            # 8. Close observability bus
            try:
                await self._observability.close()
            except AgentRuntimeError as exc:
                observability_error = observability_error or exc
            if observability_error is not None:
                raise observability_error

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
        """Return the provider capabilities available in Phase 2."""

        return RuntimeCapabilities(
            structured_output=True,
            ephemeral_sessions=True,
            ephemeral_tasks=True,
            persistent_sessions=True,
            streaming=True,
            interruption=True,
            host_tools=self._dynamic_tools_compatibility.supported,
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

        spec = self._profile_spec(profile)
        validate_model_profile(spec, profile)
        return _CodexModel(self, profile, level, InvocationConfig())

    async def brain(
        self, config: InvocationConfig | None = None, *, level: str = "medium"
    ) -> RuntimeModel[str]:
        """Return the ephemeral brain model after checking lifecycle."""

        self._require_started()
        self._profile_spec("brain")
        return _CodexModel(self, "brain", level, config or InvocationConfig())

    async def session(
        self,
        profile: str = "session",
        *,
        level: str = "medium",
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> _CodexSession:
        """Create a persistent Codex session with an opaque descriptor."""

        self._require_started()
        spec = self._profile_spec(profile)
        validate_session_profile(spec, profile)
        tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
        self._ensure_profile_executable(spec, tool_snapshot is not None)
        binding = self._resolve_binding(profile, level, config)
        model, effort = binding.model, binding.effort
        workspace = create_workspace()
        try:
            if tool_snapshot is None:
                thread = await self._require_started().thread_start(
                    ephemeral=False,
                    model=model,
                    cwd=str(workspace),
                    approval_mode=_enum("ApprovalMode", "deny_all"),
                    sandbox=_enum("Sandbox", "read_only"),
                )
            else:  # pragma: no cover - exercised by the opt-in Codex smoke
                thread = await start_thread(
                    self._require_started(),
                    dynamic_tools=tool_snapshot,
                    ephemeral=False,
                    model=model,
                    cwd=str(workspace),
                    approvalPolicy="never",
                    sandboxPolicy="read-only",
                )
            descriptor = self._make_descriptor(
                model,
                effort,
                profile,
                level,
                spec.context.value,
                spec.security_policy.value,
                str(getattr(thread, "id", "")),
            )
            state = _SessionState(
                self,
                thread,
                descriptor,
                model,
                effort,
                profile,
                level,
                spec.context.value,
                spec.security_policy.value,
                workspace,
                config or InvocationConfig(),
                tool_snapshot,
                tool_executor,
            )
            self._sessions[descriptor] = state
            await self._dispatch(
                self._emit(RuntimeEventKind.SESSION_CREATED, session_id=descriptor)
            )
            return _CodexSession(state)
        except Exception as exc:
            remove_workspace(workspace)
            raise _map_sdk_error(exc, "session creation") from exc

    def _make_descriptor(
        self,
        model: str,
        effort: str,
        profile: str,
        level: str,
        context_policy: str,
        security_policy: str,
        provider_id: str,
        descriptor_nonce: str | None = None,
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
            level=level,
            context_policy=context_policy,
            security_policy=security_policy,
            descriptor_nonce=descriptor_nonce,
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

    async def resume_session(
        self,
        descriptor: str,
        *,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> _CodexSession:
        """Validate and resume a persistent session descriptor."""

        sdk = self._require_started()
        if not isinstance(descriptor, str):
            raise TypeError("Session descriptor must be a string")
        if descriptor.startswith("task_"):
            raise SessionNotFoundError(
                f"Task '{descriptor}' is ephemeral and cannot be resumed as a session"
            )
        raw = descriptor
        decoded = SessionCodec.decode(raw)
        if (
            decoded.provider != "codex"
            or decoded.identity_fingerprint != self._identity_fingerprint
        ):
            raise SessionMismatchError("Session identity does not match the runtime")
        spec = self._profile_spec(decoded.profile)
        tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
        self._ensure_profile_executable(spec, tool_snapshot is not None)
        if (
            decoded.context_policy != spec.context.value
            or decoded.security_policy != spec.security_policy.value
        ):
            raise SessionMismatchError("Session policy does not match the runtime")
        binding = self._resolve_binding(decoded.profile, decoded.level)
        model = binding.model
        expected = self._configuration_fingerprint(
            model,
            binding.effort,
            decoded.profile,
            spec.context.value,
            spec.security_policy.value,
        )
        if decoded.configuration_fingerprint != expected:
            raise SessionMismatchError("Session configuration does not match the runtime")
        existing = self._sessions.get(raw)
        if (
            existing is not None
            and not existing.deleted
            and (existing.active is not None or existing.lock.locked())
        ):
            raise SessionBusyError("Cannot resume an active Codex session")
        workspace = create_workspace()
        try:
            if tool_snapshot is None:
                if self.experimental_dynamic_tools:
                    thread = await resume_thread(
                        sdk,
                        decoded.provider_session_id,
                        dynamic_tools=None,
                        model=model,
                        cwd=str(workspace),
                        approvalPolicy="never",
                        sandboxPolicy="read-only",
                    )
                else:
                    thread = await sdk.thread_resume(
                        decoded.provider_session_id,
                        model=model,
                        cwd=str(workspace),
                        approval_mode=_enum("ApprovalMode", "deny_all"),
                        sandbox=_enum("Sandbox", "read_only"),
                    )
            else:  # pragma: no cover - exercised by the opt-in Codex smoke
                assert tool_executor is not None
                bridge = CodexToolBridge(tool_executor)
                install_bridge(sdk, bridge)
                thread = await resume_thread(
                    sdk,
                    decoded.provider_session_id,
                    dynamic_tools=tool_snapshot,
                    model=model,
                    cwd=str(workspace),
                    approvalPolicy="never",
                    sandboxPolicy="read-only",
                )
        except Exception as exc:
            remove_workspace(workspace)
            raise SessionNotFoundError("Codex session was not found") from exc
        if existing is not None and not existing.deleted:
            previous_workspace = existing.workspace
            existing.thread = thread
            existing.workspace = workspace
            existing.closed_handles = 0
            existing.model = model
            existing.effort = binding.effort
            existing.context_policy = spec.context.value
            existing.security_policy = spec.security_policy.value
            existing.tool_snapshot = tool_snapshot
            existing.tool_executor = tool_executor
            existing.generation += 1
            state = existing
            remove_workspace(previous_workspace)
        else:
            state = _SessionState(
                self,
                thread,
                raw,
                model,
                binding.effort,
                decoded.profile,
                decoded.level,
                spec.context.value,
                spec.security_policy.value,
                workspace,
                InvocationConfig(),
                tool_snapshot,
                tool_executor,
            )
            self._sessions[raw] = state
        await self._dispatch(self._emit(RuntimeEventKind.SESSION_RESUMED, session_id=raw))
        return _CodexSession(state)

    async def task(
        self,
        profile: str = "controlled_agent",
        *,
        level: str = "medium",
        instructions: str | None = None,
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeTask[Any]:
        """Create a task-scoped ephemeral controlled agent.

        Args:
            profile: Name of the execution profile (defaults to 'controlled_agent').
            level: Logical reasoning effort level ('low', 'medium', 'high', 'ultra').
            instructions: Optional initial task instructions frozen for the task lifetime.
            config: Optional default invocation configuration for turns in this task.
            registry: Optional host-tool registry (mandatory for controlled tool profiles).
            executor: Optional host-tool executor for dispatching tool calls.

        Returns:
            An active RuntimeTask instance bound to a fresh provider task context.

        Raises:
            CapabilityError: If capabilities, lifecycle boundaries, or tool bindings fail validation.
        """
        self._require_started()
        capabilities = await self.capabilities()
        if not capabilities.ephemeral_tasks:
            raise CapabilityError(
                f"Runtime '{self.name}' does not support ephemeral multi-turn tasks."
            )
        spec = self._profile_spec(profile)
        validate_task_profile(spec, profile)
        if registry is None:
            raise CapabilityError("A host-tool registry is required for this profile")
        tool_snapshot, tool_executor = self._tool_binding(spec, registry, executor)
        assert tool_snapshot is not None
        self._ensure_profile_executable(spec, tool_snapshot is not None)
        binding = self._resolve_binding(profile, level, config)
        model, effort = binding.model, binding.effort
        workspace = create_workspace()
        try:
            thread = await start_thread(
                self._require_started(),
                dynamic_tools=tool_snapshot,
                ephemeral=True,
                developer_instructions=instructions,
                model=model,
                cwd=str(workspace),
                approvalPolicy="never",
                sandboxPolicy="read-only",
            )
        except Exception as exc:
            remove_workspace(workspace)
            raise _map_sdk_error(exc, "task creation") from exc

        task_id = f"task_{uuid4().hex}"
        task = _CodexTask(
            runtime=self,
            task_id=task_id,
            thread=thread,
            model=model,
            effort=effort,
            profile=profile,
            level=level,
            instructions=instructions,
            config=config or InvocationConfig(),
            workspace=workspace,
            tool_snapshot=tool_snapshot,
            tool_executor=tool_executor,
            spec=spec,
        )
        self._tasks[task_id] = task
        await self._dispatch(self._emit(RuntimeEventKind.TASK_STARTED, task_id=task_id))
        return task

    def get_task(self, task_id: str) -> RuntimeTask[Any]:
        """Resolve an active, in-memory task by its identifier.

        Args:
            task_id: The unique task identifier string.

        Returns:
            The active RuntimeTask instance.

        Raises:
            SessionNotFoundError: If the task is missing or already closed.
        """
        task = self._tasks.get(task_id)
        if task is None or getattr(task, "_state", None) != TaskState.OPEN:
            raise SessionNotFoundError(f"Task '{task_id}' not found or already closed")
        return task

    async def migrate_session(
        self, session_id: str, *, profile: str, level: str = "medium", security_policy: str
    ) -> _CodexSession:
        """Rebind one existing Codex thread without replaying or copying history."""

        sdk = self._require_started()
        old = SessionCodec.decode(session_id)
        if old.provider != "codex" or old.identity_fingerprint != self._identity_fingerprint:
            raise SessionMismatchError("Only same-identity Codex sessions can migrate")
        state = self._sessions.get(session_id)
        if state is not None and state.deleted:
            state = None
        if state is not None and (state.active is not None or state.lock.locked()):
            raise SessionBusyError("Cannot migrate an active Codex session")
        target = self._profile_spec(profile)
        if not target.persistent:
            raise CapabilityError("Session migration requires a persistent profile")
        self._ensure_profile_executable(target)
        if (
            security_policy != old.security_policy
            or security_policy != target.security_policy.value
        ):
            raise CapabilityError("Session migration cannot expand or change permissions")
        binding = self._resolve_binding(profile, level)
        thread_id = old.provider_session_id
        previous_workspace = state.workspace if state is not None else None
        workspace = create_workspace()
        try:
            thread = await sdk.thread_resume(
                thread_id,
                model=binding.model,
                cwd=str(workspace),
                approval_mode=_enum("ApprovalMode", "deny_all"),
                sandbox=_enum("Sandbox", "read_only"),
            )
        except Exception as exc:
            remove_workspace(workspace)
            raise _map_sdk_error(exc, "session migration") from exc
        new_descriptor = self._make_descriptor(
            binding.model,
            binding.effort,
            profile,
            level,
            target.context.value,
            target.security_policy.value,
            thread_id,
            descriptor_nonce=uuid4().hex,
        )
        if state is None:
            state = _SessionState(
                self,
                thread,
                new_descriptor,
                binding.model,
                binding.effort,
                profile,
                level,
                target.context.value,
                target.security_policy.value,
                workspace,
                InvocationConfig(),
            )
        else:
            self._sessions.pop(session_id, None)
            state.thread = thread
            state.descriptor = new_descriptor
            state.model = binding.model
            state.effort = binding.effort
            state.profile = profile
            state.level = level
            state.context_policy = target.context.value
            state.security_policy = target.security_policy.value
            state.workspace = workspace
            state.config = InvocationConfig()
            state.generation += 1
        self._sessions[new_descriptor] = state
        if previous_workspace is not None:
            remove_workspace(previous_workspace)
        await self._dispatch(
            self._emit(
                RuntimeEventKind.SESSION_MIGRATED,
                session_id=new_descriptor,
                metadata={
                    "old_session_id": session_id,
                    "new_session_id": new_descriptor,
                    "old_profile": old.profile,
                    "new_profile": profile,
                    "old_level": old.level,
                    "new_level": level,
                },
            )
        )
        return _CodexSession(state)

    def _resolve_model(self, config: InvocationConfig | None) -> str:
        """Resolve and validate a configured model."""

        return self._resolve_binding("brain", "medium", config).model

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

    def _profile_spec(self, profile: str) -> Any:
        """Resolve a built-in or configured custom profile."""

        try:
            return self._config.profile_spec(profile)
        except ConfigurationError:
            return profile_spec(profile)

    def _resolve_binding(
        self,
        profile: str,
        level: str,
        config: InvocationConfig | None = None,
        *,
        default_model: str | None = None,
    ) -> _ResolvedBinding:
        """Resolve and validate one immutable profile/model/effort binding."""

        spec = self._profile_spec(profile)
        mapping = self._config.lookup(profile, level)
        selected_model = (
            config.model
            if config is not None and config.model is not None
            else default_model or mapping.model
        )
        selected_effort = (
            config.reasoning_effort
            if config is not None and config.reasoning_effort is not None
            else mapping.reasoning_effort
        )
        self._validate_model_effort(str(selected_model), str(selected_effort))
        return _ResolvedBinding(
            profile=profile,
            level=str(level),
            model=str(selected_model),
            effort=str(selected_effort),
            spec=spec,
        )

    def _validate_model_effort(self, model: str, effort: str) -> None:
        """Validate a concrete catalog model and provider reasoning effort."""

        if model not in self._catalog:
            raise CapabilityError(f"Unknown Codex model: {model}")
        supported = {
            _effort_value(value)
            for value in (getattr(self._catalog[model], "supported_reasoning_efforts", ()) or ())
        }
        if supported and effort not in supported:
            raise CapabilityError(f"Unsupported reasoning effort: {effort}")

    def _ensure_profile_executable(self, spec: Any, has_tools: bool = False) -> None:
        """Reject Phase 2 profiles whose permissions are not implemented."""

        if (
            has_tools
            and spec.host_tools.value in {"controlled", "explicit"}
            and self.experimental_dynamic_tools
        ):
            return
        if spec.security_policy != "isolated" or spec.host_tools.value != "disabled":
            raise CapabilityError("The requested profile requires a deferred Phase 2 capability")

    def _tool_binding(
        self,
        spec: Any,
        registry: ToolRegistry | None,
        executor: ToolExecutor | None,
    ) -> tuple[ToolSnapshot | None, ToolExecutor | None]:
        """Validate and freeze an optional host-tool binding for one view/session."""

        if registry is None and executor is None:
            if spec.host_tools.value != "disabled":
                raise CapabilityError("A host-tool registry is required for this profile")
            return None, None
        if spec.host_tools.value not in {"controlled", "explicit"}:
            raise CapabilityError("The selected profile does not permit host-managed tools")
        if not self.experimental_dynamic_tools:
            raise CapabilityError("Codex dynamic tools require experimental_dynamic_tools=True")
        if not self._dynamic_tools_compatibility.supported:
            raise CapabilityError(
                f"Codex dynamic tools are unavailable: {self._dynamic_tools_compatibility.reason}"
            )
        if registry is not None:
            snapshot = registry.snapshot()
        else:
            assert executor is not None
            snapshot = executor.snapshot
        if not snapshot.definitions():
            raise CapabilityError("A host-tool registry must contain at least one tool")
        if executor is None:
            bound_executor = ToolExecutor(snapshot, frozen=True)
        elif executor.snapshot.provider_definitions() != snapshot.provider_definitions():
            raise CapabilityError("Tool executor does not match the registry snapshot")
        else:
            bound_executor = executor.clone(snapshot=snapshot, freeze=True)
        return snapshot, bound_executor

    def _register_run(self, run: TurnRun) -> None:
        """Register one active turn for coordinated cleanup."""

        self._active_runs[run.invocation_id] = run

    def _unregister_run(self, run: TurnRun) -> None:
        """Remove one completed turn from the active registry."""

        self._active_runs.pop(run.invocation_id, None)

    async def _dispatch(self, event: RuntimeEvent) -> RuntimeEvent:
        """Dispatch one event through the shared observer bus."""

        return await self._observability.emit(event)

    def _emit(
        self,
        kind: RuntimeEventKind,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Record a provider-neutral lifecycle event."""

        identity = self._identity or RuntimeIdentity("codex", "uninitialized")
        event = RuntimeEvent(
            kind=kind,
            event_id=f"runtime:{self._sequence}",
            sequence=self._sequence,
            occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            runtime=identity,
            session_id=session_id,
            metadata=metadata or {},
            task_id=task_id,
        )
        self._sequence += 1
        self.events.append(event)
        return event


class _CodexModel:
    """Internal model implementation shared by brain and session factories."""

    def __init__(
        self,
        runtime: CodexRuntime,
        profile: str,
        level: str,
        config: InvocationConfig,
        tool_snapshot: ToolSnapshot | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        """Store model configuration without contacting Codex."""

        self.runtime = runtime
        self.profile = profile
        self.level = level
        self.config = config
        self._bound_default_model = runtime.default_model
        self._tool_snapshot = tool_snapshot
        self._tool_executor = tool_executor

    def with_structured_output(
        self, schema: Any, *, policy: StructuredOutputPolicy | None = None
    ) -> RuntimeModel[Any]:
        """Return a structured facade after validating its schema locally."""

        if self._tool_snapshot is not None:
            raise CapabilityError("Structured output cannot be combined with host-managed tools")
        from ._structured import StructuredCodexModel

        return StructuredCodexModel(self, schema, policy)

    def with_tools(
        self,
        registry: ToolRegistry,
        *,
        executor: ToolExecutor | None = None,
    ) -> RuntimeModel[Any]:
        """Return an immutable Codex model view bound to a registry snapshot."""

        spec = self.runtime._profile_spec(self.profile)
        snapshot, bound_executor = self.runtime._tool_binding(spec, registry, executor)
        assert snapshot is not None and bound_executor is not None
        return _CodexModel(
            self.runtime,
            self.profile,
            self.level,
            self.config,
            snapshot,
            bound_executor,
        )

    async def effective_capabilities(self) -> RuntimeCapabilities:
        """Return effective capabilities for this model profile.

        Applies profile restrictions, feature flags, and tool bindings to the
        provider-level capabilities.

        Returns:
            RuntimeCapabilities effective for this model instance.
        """
        capabilities = await self.runtime.capabilities()
        spec = self.runtime._profile_spec(self.profile)
        has_tools = (
            self._tool_snapshot is not None
            and bool(self._tool_snapshot.definitions())
            and capabilities.host_tools
            and self.runtime.experimental_dynamic_tools
            and spec.host_tools.value in {"controlled", "explicit"}
        )
        allows_structured = (
            self._tool_snapshot is None
            and spec.security_policy == "isolated"
            and spec.host_tools.value == "disabled"
        )
        return RuntimeCapabilities(
            structured_output=bool(capabilities.structured_output and allows_structured),
            ephemeral_sessions=capabilities.ephemeral_sessions,
            ephemeral_tasks=capabilities.ephemeral_tasks,
            persistent_sessions=capabilities.persistent_sessions,
            streaming=capabilities.streaming,
            interruption=capabilities.interruption,
            host_tools=has_tools,
            native_tools=False,
            sandbox=capabilities.sandbox,
            usage_reporting=capabilities.usage_reporting,
        )

    async def _start_run(
        self,
        value: str | RuntimeInput,
        include_raw: bool,
        config: InvocationConfig | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> tuple[TurnRun, Path]:
        """Create an ephemeral thread and start one async turn."""

        sdk = self.runtime._require_started()
        if self.profile == "structured" and output_schema is None:
            raise ConfigurationError(
                "Structured profile requires an output schema", path="output_schema"
            )
        prompt, instructions = serialize_input(value)
        effective = _merge_invocation_config(self.config, config)
        self.runtime._ensure_profile_executable(
            self.runtime._profile_spec(self.profile), self._tool_snapshot is not None
        )
        binding = self.runtime._resolve_binding(
            self.profile,
            self.level,
            effective,
            default_model=self._bound_default_model,
        )
        model, effort = binding.model, binding.effort
        workspace = create_workspace()
        bridge: CodexToolBridge | None = None
        mux: CodexToolMux | None = None
        try:
            if self._tool_snapshot is None:
                thread = await sdk.thread_start(
                    ephemeral=True,
                    model=model,
                    developer_instructions=instructions,
                    cwd=str(workspace),
                    approval_mode=_enum("ApprovalMode", "deny_all"),
                    sandbox=_enum("Sandbox", "read_only"),
                )
            else:  # pragma: no cover - exercised by the opt-in Codex smoke
                assert self._tool_executor is not None
                bridge = CodexToolBridge(self._tool_executor)
                mux = install_bridge(sdk, bridge)
                thread = await start_thread(
                    sdk,
                    dynamic_tools=self._tool_snapshot,
                    ephemeral=True,
                    model=model,
                    developer_instructions=instructions,
                    cwd=str(workspace),
                    approvalPolicy="never",
                    sandboxPolicy="read-only",
                )
            handle = await thread.turn(
                prompt,
                model=model,
                effort=effort,
                output_schema=output_schema,
                approval_mode=_enum("ApprovalMode", "deny_all"),
                sandbox=_enum("Sandbox", "read_only"),
            )
        except Exception as exc:
            if bridge is not None:
                bridge.unbind()
            if mux is not None and bridge is not None:
                with suppress(Exception):
                    mux.unregister(bridge)
            remove_workspace(workspace)
            raise _map_sdk_error(exc, "brain invocation") from exc
        invocation_id = str(getattr(handle, "id", "")) or uuid4().hex
        if bridge is not None and mux is not None:
            bridge.invocation_id = invocation_id
            mux.register(
                bridge,
                thread_id=str(getattr(thread, "id", "")),
                turn_id=invocation_id,
                invocation_id=invocation_id,
            )
        run = TurnRun(
            runtime_name="codex",
            identity=self.runtime.identity,
            handle=handle,
            invocation_id=invocation_id,
            model=model,
            profile=self.profile,
            effort=effort,
            include_raw=include_raw,
            event_sink=self.runtime._dispatch,
            context_policy=binding.spec.context.value,
            security_policy=binding.spec.security_policy.value,
            invocation_metadata=effective.metadata,
            structured_output=output_schema is not None,
        )
        run.provider_thread = thread
        cleaned_up = False

        def _cleanup_turn() -> None:
            """Clean up turn-scoped resources idempotently."""
            nonlocal cleaned_up
            if cleaned_up:
                return
            cleaned_up = True
            if bridge is not None and mux is not None:
                with suppress(Exception):
                    mux.unregister(bridge)
            if self._tool_executor is not None:
                with suppress(Exception):
                    self._tool_executor.end_invocation(invocation_id)

        run.cleanup = _cleanup_turn
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

        effective_config = _merge_invocation_config(self.config, config)
        effective_raw = bool(effective_config.include_raw if include_raw is None else include_raw)
        run, workspace = await self._start_run(input, effective_raw, effective_config)
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
            if run.cleanup is not None:
                with suppress(Exception):
                    run.cleanup()
                run.cleanup = None
            if run.terminal_status is None:
                await self._interrupt_or_invalidate(run)
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

        effective_config = _merge_invocation_config(self.config, config)
        effective_raw = bool(effective_config.include_raw if include_raw is None else include_raw)
        run, workspace = await self._start_run(input, effective_raw, effective_config)
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
            if run.cleanup is not None:
                with suppress(Exception):
                    run.cleanup()
                run.cleanup = None
            if run.terminal_status is None:
                await self._interrupt_or_invalidate(run)
            self.runtime._unregister_run(run)
            remove_workspace(workspace)


class _CodexSession:
    """Internal persistent session handle."""

    def __init__(self, state: _SessionState) -> None:
        """Bind a public handle to shared persistent state."""

        self._state = state
        self._closed = False
        self._generation = state.generation
        self._descriptor = state.descriptor

    @property
    def id(self) -> str:
        """Return the opaque descriptor identifier."""

        return self._descriptor

    @property
    def descriptor(self) -> str:
        """Return the opaque descriptor."""

        return self._descriptor

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
            prompt = self._serialize_context(runtime_input)
            run = await self._start_turn(prompt, config, include_raw)
            try:
                effective = self._effective_config(config, include_raw)
                timeout = effective.timeout_seconds
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
            except asyncio.CancelledError as exc:
                await self._interrupt_or_invalidate(run)
                raise CancellationError("Codex session turn was cancelled") from exc
            finally:
                if run is not None and run.cleanup is not None:
                    with suppress(Exception):
                        run.cleanup()
                    run.cleanup = None
                self._state.active = None
                self._state.runtime._unregister_run(run)

    async def _start_turn(
        self, prompt: str, config: InvocationConfig | None, include_raw: bool | None
    ) -> TurnRun:
        """Start one turn on the shared persistent thread."""

        effective = self._effective_config(config, include_raw)
        handle = await self._state.thread.turn(
            prompt,
            model=self._state.model,
            effort=self._state.effort,
            approval_mode=_enum("ApprovalMode", "deny_all"),
            sandbox=_enum("Sandbox", "read_only"),
        )
        bridge: CodexToolBridge | None = None
        mux: CodexToolMux | None = None
        invocation_id = str(getattr(handle, "id", "")) or uuid4().hex
        if self._state.tool_executor is not None:
            bridge = CodexToolBridge(
                self._state.tool_executor,
                invocation_id=invocation_id,
                session_id=self.id,
            )
            mux = install_bridge(self._state.runtime._require_started(), bridge)
            mux.register(
                bridge,
                thread_id=str(getattr(self._state.thread, "id", "")),
                turn_id=invocation_id,
                invocation_id=invocation_id,
                session_id=self.id,
            )
        run = TurnRun(
            runtime_name="codex",
            identity=self._state.runtime.identity,
            handle=handle,
            invocation_id=invocation_id,
            model=self._state.model,
            profile=self._state.profile,
            effort=self._state.effort,
            session_id=self.id,
            include_raw=bool(effective.include_raw),
            event_sink=self._state.runtime._dispatch,
            context_policy=self._state.context_policy,
            security_policy=self._state.security_policy,
            invocation_metadata=effective.metadata,
            ephemeral=False,
        )
        if bridge is not None and mux is not None:
            cleaned_up = False

            def _cleanup_session_turn() -> None:
                """Clean up session turn-scoped resources idempotently."""
                nonlocal cleaned_up
                if cleaned_up:
                    return
                cleaned_up = True
                if bridge is not None and mux is not None:
                    with suppress(Exception):
                        mux.unregister(bridge)
                if self._state.tool_executor is not None:
                    with suppress(Exception):
                        self._state.tool_executor.end_invocation(invocation_id)

            run.cleanup = _cleanup_session_turn
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
            prompt = self._serialize_context(runtime_input)
            run = await self._start_turn(prompt, config, include_raw)
            timeout = self._effective_config(config, include_raw).timeout_seconds
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
                if run.cleanup is not None:
                    with suppress(Exception):
                        run.cleanup()
                    run.cleanup = None
                if run.terminal_status is None:
                    await self._interrupt_or_invalidate(run)
                self._state.runtime._unregister_run(run)
            self._state.active = None
            self._state.lock.release()

    def _validate_user_input(self, value: RuntimeInput) -> None:
        """Reject system, assistant, and tool replay in persistent sessions."""

        policy = self._state.context_policy
        if policy == "runtime" and any(message.role != "user" for message in value.messages):
            raise ContextPolicyError("Runtime Codex sessions accept user messages only")
        if policy == "hybrid" and any(
            message.role not in {"system", "user"} for message in value.messages
        ):
            raise ContextPolicyError("Hybrid Codex sessions reject assistant/tool replay")

    def _serialize_context(self, value: RuntimeInput) -> str:
        """Serialize the current turn according to the session context policy."""

        prompt, instructions = serialize_input(value)
        if self._state.context_policy == "hybrid" and instructions:
            return f"[system]\n{instructions}\n\n{prompt}"
        return prompt

    def _effective_config(
        self, config: InvocationConfig | None, include_raw: bool | None
    ) -> InvocationConfig:
        """Merge invocation metadata while keeping session model binding frozen."""

        effective = _merge_invocation_config(self._state.config, config)
        if config is not None and config.model is not None and config.model != self._state.model:
            raise CapabilityError("Session model configuration is immutable")
        if (
            config is not None
            and config.reasoning_effort is not None
            and str(config.reasoning_effort) != self._state.effort
        ):
            raise CapabilityError("Session reasoning configuration is immutable")
        if include_raw is not None:
            effective = _merge_invocation_config(
                effective, InvocationConfig(include_raw=include_raw)
            )
        return effective

    def _ensure_open(self) -> None:
        """Reject operations after local close or provider deletion."""

        if self._closed or self._state.deleted or self._generation != self._state.generation:
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

        if self._generation != self._state.generation:
            self._closed = True
            return
        if not self._closed:
            active = self._state.active
            if active is not None:
                await active.interrupt()
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(active.wait_finished(), timeout=5.0)
            self._closed = True
            self._state.closed_handles += 1
            remove_workspace(self._state.workspace)
            await self._state.runtime._dispatch(
                self._state.runtime._emit(RuntimeEventKind.SESSION_CLOSED, session_id=self.id)
            )

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
            await self._state.runtime._dispatch(
                self._state.runtime._emit(RuntimeEventKind.SESSION_ARCHIVED, session_id=self.id)
            )

    async def delete(self) -> None:
        """Delete the provider thread through the isolated compatibility shim."""

        if self._state.deleted or self._generation != self._state.generation:
            raise SessionNotFoundError("Codex session handle is closed or deleted")
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
            await self._state.runtime._dispatch(
                self._state.runtime._emit(RuntimeEventKind.SESSION_DELETED, session_id=self.id)
            )


class _CodexTask(RuntimeTask[str]):
    """Internal task handle implementing RuntimeTask for Codex."""

    def __init__(
        self,
        runtime: CodexRuntime,
        task_id: str,
        *,
        thread: Any,
        model: str,
        effort: str,
        profile: str,
        level: str,
        instructions: str | None,
        config: InvocationConfig,
        workspace: Path,
        tool_snapshot: ToolSnapshot | None,
        tool_executor: ToolExecutor | None,
        spec: Any,
    ) -> None:
        """Initialize an active Codex task handle.

        Args:
            runtime: Owning CodexRuntime instance.
            task_id: Unique task identifier string.
            thread: Live Codex SDK provider thread.
            model: Concrete model name.
            effort: Reasoning effort level.
            profile: Execution profile name.
            level: Logical level name.
            instructions: Initial frozen task instructions.
            config: Default invocation configuration.
            workspace: Path to isolated task workspace.
            tool_snapshot: Optional frozen tool definitions.
            tool_executor: Optional host tool executor.
            spec: Profile specification.
        """
        self.runtime = runtime
        self._id = task_id
        self._thread = thread
        self._model = model
        self._effort = effort
        self._profile = profile
        self._level = level
        self._instructions = instructions
        self._config = config
        self._workspace = workspace
        self._tool_snapshot = tool_snapshot
        self._tool_executor = tool_executor
        self._spec = spec
        self._state = TaskState.OPEN
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._close_event = asyncio.Event()
        self._active_run: TurnRun | None = None
        self._active_invocation_id: str | None = None
        self._diagnostics: list[RuntimeDiagnostic] = []

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

    @property
    def diagnostics(self) -> tuple[RuntimeDiagnostic, ...]:
        """Return a snapshot of diagnostics recorded during task operations."""
        return tuple(self._diagnostics)

    def _record_diagnostic(
        self,
        *,
        code: str,
        message: str,
        exc: Exception,
    ) -> RuntimeDiagnostic:
        """Record a sanitized diagnostic for a task cleanup failure.

        Args:
            code: Stable low-cardinality diagnostic code.
            message: Safe human-readable summary without exception text.
            exc: Underlying exception used only for type classification.

        Returns:
            The created and recorded RuntimeDiagnostic.
        """
        diagnostic = RuntimeDiagnostic(
            code=code,
            message=message,
            severity=DiagnosticSeverity.WARNING,
            details={
                "exception_type": type(exc).__name__,
                "task_id": self._id,
            },
        )
        self._diagnostics.append(diagnostic)
        self.runtime._record_diagnostic(diagnostic)
        return diagnostic

    def _ensure_open(self) -> None:
        """Raise SessionNotFoundError if the task is closing or closed."""
        if self._state in (TaskState.CLOSING, TaskState.CLOSED):
            raise SessionNotFoundError(f"Task '{self._id}' not found or already closed")

    def _validate_config(
        self, config: InvocationConfig | None, include_raw: bool | None
    ) -> InvocationConfig:
        """Merge invocation metadata while validating prohibited overrides.

        Args:
            config: Turn invocation config.
            include_raw: Optional override to include raw payloads.

        Returns:
            Merged invocation config.

        Raises:
            ConfigurationError: If prohibited overrides are passed.
        """
        effective = _merge_invocation_config(self._config, config)
        if config is not None and config.model is not None and config.model != self._model:
            raise ConfigurationError(
                f"Cannot change model from '{self._model}' to '{config.model}' on active task"
            )
        if (
            config is not None
            and config.reasoning_effort is not None
            and str(config.reasoning_effort) != self._effort
        ):
            raise ConfigurationError(
                f"Cannot change reasoning effort from '{self._effort}' to '{config.reasoning_effort}' on active task"
            )
        if include_raw is not None:
            effective = _merge_invocation_config(
                effective, InvocationConfig(include_raw=include_raw)
            )
        return effective

    async def ainvoke(
        self,
        input: str | RuntimeInput,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[str]:
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
        if self._lock.locked():
            raise SessionBusyError("Task already has an active turn")
        effective = self._validate_config(config, include_raw)
        validated_input = validate_task_input(input)

        async with self._lock:
            self._ensure_open()
            prompt, _ = serialize_input(validated_input)
            run = await self._start_turn(prompt, effective)
            try:
                timeout = effective.timeout_seconds
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
                await self._interrupt_active_run(run)
                raise RuntimeTimeoutError("Codex task turn timed out") from exc
            except asyncio.CancelledError as exc:
                await self._interrupt_active_run(run)
                raise CancellationError("Codex task turn was cancelled") from exc
            finally:
                if run.cleanup is not None:
                    run.cleanup()
                self._active_run = None
                self._active_invocation_id = None
                self.runtime._unregister_run(run)

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
        if self._lock.locked():
            raise SessionBusyError("Task already has an active turn")
        effective = self._validate_config(config, include_raw)
        validated_input = validate_task_input(input)

        await self._lock.acquire()
        run: TurnRun | None = None
        try:
            self._ensure_open()
            prompt, _ = serialize_input(validated_input)
            run = await self._start_turn(prompt, effective)
            timeout = effective.timeout_seconds
            if timeout is None:
                async for event in run.events():
                    yield event
            else:
                async with asyncio.timeout(timeout):
                    async for event in run.events():
                        yield event
        except TimeoutError as exc:
            if run is not None:
                await self._interrupt_active_run(run)
            raise RuntimeTimeoutError("Codex task stream timed out") from exc
        except asyncio.CancelledError as exc:
            if run is not None:
                await self._interrupt_active_run(run)
            raise CancellationError("Codex task stream was cancelled") from exc
        finally:
            if run is not None:
                if run.cleanup is not None:
                    run.cleanup()
                if run.terminal_status is None:
                    await self._interrupt_active_run(run)
                self.runtime._unregister_run(run)
            self._active_run = None
            self._active_invocation_id = None
            self._lock.release()

    async def _start_turn(self, prompt: str, effective: InvocationConfig) -> TurnRun:
        """Start one turn on the shared task thread.

        Args:
            prompt: Serialized prompt text.
            effective: Merged per-turn invocation configuration.

        Returns:
            An active TurnRun handle.

        Raises:
            SessionNotFoundError: If the task is closing or closed.
        """
        handle = await self._thread.turn(
            prompt,
            model=self._model,
            effort=self._effort,
            approval_mode=_enum("ApprovalMode", "deny_all"),
            sandbox=_enum("Sandbox", "read_only"),
        )
        try:
            if self._state in (TaskState.CLOSING, TaskState.CLOSED):
                raise SessionNotFoundError(f"Task '{self.id}' not found or already closed")
            bridge: CodexToolBridge | None = None
            mux: CodexToolMux | None = None
            invocation_id = str(getattr(handle, "id", "")) or uuid4().hex
            self._active_invocation_id = invocation_id
            if self._tool_executor is not None:
                bridge = CodexToolBridge(
                    self._tool_executor,
                    invocation_id=invocation_id,
                    task_id=self.id,
                )
                mux = install_bridge(self.runtime._require_started(), bridge)
                mux.register(
                    bridge,
                    thread_id=str(getattr(self._thread, "id", "")),
                    turn_id=invocation_id,
                    invocation_id=invocation_id,
                    task_id=self.id,
                )
            run = TurnRun(
                runtime_name="codex",
                identity=self.runtime.identity,
                handle=handle,
                invocation_id=invocation_id,
                model=self._model,
                profile=self._profile,
                effort=self._effort,
                session_id=None,
                task_id=self.id,
                include_raw=bool(effective.include_raw),
                event_sink=self.runtime._dispatch,
                context_policy=self._spec.context.value,
                security_policy=self._spec.security_policy.value,
                invocation_metadata=effective.metadata,
                ephemeral=True,
            )
            run.provider_thread = self._thread
            if bridge is not None and mux is not None:
                cleaned_up = False

                def _cleanup_turn() -> None:
                    """Clean up task turn-scoped resources idempotently."""
                    nonlocal cleaned_up
                    if cleaned_up:
                        return
                    cleaned_up = True
                    assert mux is not None and bridge is not None
                    mux.unregister(bridge)
                    assert self._tool_executor is not None
                    self._tool_executor.end_invocation(invocation_id)

                run.cleanup = _cleanup_turn
            self._active_run = run
            self.runtime._register_run(run)
            return run
        except BaseException:
            with suppress(Exception):
                await handle.interrupt()
            raise

    async def _interrupt_active_run(self, run: TurnRun) -> None:
        """Interrupt an active turn without closing the task."""
        try:
            await asyncio.wait_for(run.interrupt(), timeout=5.0)
            await asyncio.wait_for(run.wait_finished(), timeout=5.0)
        except Exception:
            pass

    async def interrupt(self) -> None:
        """Interrupt any active turn on this task.

        Raises:
            SessionNotFoundError: If the task is closing or closed.
        """
        self._ensure_open()
        if self._active_run is not None:
            await self._interrupt_active_run(self._active_run)

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
            # 1. Cancel active turn directly via internal cancellation primitive
            if self._active_run is not None:
                try:
                    await asyncio.wait_for(self._active_run.interrupt(), timeout=5.0)
                    await asyncio.wait_for(self._active_run.wait_finished(), timeout=5.0)
                except Exception as exc:  # noqa: BLE001
                    self._record_diagnostic(
                        code="task.cleanup.interrupt_failed",
                        message="Failed to interrupt active turn during task teardown",
                        exc=exc,
                    )

            # 2. Wait for any in-flight startup or active turn to complete before destroying resources
            async with self._lock:
                # 3. Cleanup turn-level resources (mux route unregistration, end_invocation)
                if self._active_run is not None and self._active_run.cleanup is not None:
                    try:
                        self._active_run.cleanup()
                    except Exception as exc:  # noqa: BLE001
                        self._record_diagnostic(
                            code="task.cleanup.tool_state_failed",
                            message="Failed to clean up tool state during task teardown",
                            exc=exc,
                        )
                elif self._tool_executor is not None and self._active_invocation_id is not None:
                    try:
                        self._tool_executor.end_invocation(self._active_invocation_id)
                    except Exception as exc:  # noqa: BLE001
                        self._record_diagnostic(
                            code="task.cleanup.tool_state_failed",
                            message="Failed to clean up tool state during task teardown",
                            exc=exc,
                        )
                # 4. Release/destroy provider task context if supported
                try:
                    sdk = getattr(self.runtime, "_sdk", None)
                    if sdk is not None:
                        thread_id = str(getattr(self._thread, "id", ""))
                        if thread_id:
                            await delete_thread(sdk, thread_id)
                except Exception as exc:  # noqa: BLE001
                    self._record_diagnostic(
                        code="task.cleanup.provider_delete_failed",
                        message="Failed to delete provider context during task teardown",
                        exc=exc,
                    )
                # 5. Remove temporary workspace
                try:
                    remove_workspace(self._workspace)
                except Exception as exc:  # noqa: BLE001
                    self._record_diagnostic(
                        code="task.cleanup.workspace_failed",
                        message="Failed to remove task workspace directory during task teardown",
                        exc=exc,
                    )
                # 6. Remove task from runtime active registry
                self.runtime._tasks.pop(self.id, None)
        finally:
            self._state = TaskState.CLOSED
            self._close_event.set()
            diagnostics_meta = [
                {
                    "code": d.code,
                    "message": d.message,
                    "severity": d.severity.value,
                    "details": dict(d.details),
                }
                for d in self._diagnostics
            ]
            await self.runtime._dispatch(
                self.runtime._emit(
                    RuntimeEventKind.TASK_CLOSED,
                    task_id=self.id,
                    metadata={"diagnostics": diagnostics_meta} if diagnostics_meta else {},
                )
            )

    async def __aenter__(self) -> _CodexTask:
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
