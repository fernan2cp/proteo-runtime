"""Asynchronous event dispatch, payload projection, and health tracking."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel

from proteo_runtime.core.diagnostics import DiagnosticSeverity, RuntimeDiagnostic
from proteo_runtime.core.errors import ObservabilityError
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.observability import ObservabilityStatus
from proteo_runtime.core.types import is_secret_key

from .types import PayloadMode


@runtime_checkable
class RuntimeObserver(Protocol):
    """Async observer contract consumed by the neutral event bus."""

    async def on_event(self, event: RuntimeEvent) -> None:
        """Consume one projected runtime event."""

    async def flush(self) -> None:
        """Flush pending exporter work owned by the observer."""

    async def close(self) -> None:
        """Release observer-local resources."""


@dataclass(frozen=True, slots=True)
class ObserverBinding:
    """Bind one observer to an explicit payload policy."""

    observer: RuntimeObserver
    payload_mode: PayloadMode | str = PayloadMode.METADATA_ONLY

    def __post_init__(self) -> None:
        """Validate the observer and normalize its payload mode."""

        if not isinstance(self.observer, RuntimeObserver):
            raise TypeError("observer must implement RuntimeObserver")
        if not isinstance(self.payload_mode, PayloadMode):
            object.__setattr__(self, "payload_mode", PayloadMode(self.payload_mode))


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    """Immutable event bus configuration."""

    observers: tuple[ObserverBinding, ...] = ()
    strict: bool = False
    dispatch_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        """Validate observer uniqueness and positive timeouts."""

        bindings = tuple(self.observers)
        if any(not isinstance(binding, ObserverBinding) for binding in bindings):
            raise TypeError("observers must contain ObserverBinding values")
        identities = [id(binding.observer) for binding in bindings]
        if len(identities) != len(set(identities)):
            raise ValueError("An observer cannot be bound more than once")
        if (
            not math.isfinite(self.dispatch_timeout_seconds)
            or not math.isfinite(self.shutdown_timeout_seconds)
            or self.dispatch_timeout_seconds <= 0
            or self.shutdown_timeout_seconds <= 0
        ):
            raise ValueError("Observability timeouts must be positive")
        object.__setattr__(self, "observers", bindings)


class _FailureKind(StrEnum):
    """Internal category used to build stable diagnostics."""

    DISPATCH = "dispatch"
    FLUSH = "flush"
    CLOSE = "close"


_SENSITIVE_METADATA_KEYS = frozenset(
    {
        "text",
        "prompt",
        "response",
        "output",
        "schema",
        "tool_arguments",
        "tool_args",
        "tool_result",
        "raw",
        "provider_payload",
        "exception",
        "cause",
    }
)
_ALWAYS_EXCLUDE_KEYS = frozenset(
    {
        "provider_payload",
        "provider_headers",
        "headers",
        "descriptor",
        "session_descriptor",
        "raw",
        "exception",
        "cause",
    }
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._-]+|"
    r"((?:api[_-]?key|token|secret|password|authorization|credential)\s*[:=]\s*)[^,}\s]+"
)
_TERMINAL_KINDS = frozenset(
    {
        RuntimeEventKind.INVOCATION_COMPLETED,
        RuntimeEventKind.INVOCATION_FAILED,
        RuntimeEventKind.CANCELLED,
        RuntimeEventKind.INTERRUPTED,
    }
)


class RuntimeEventBus:
    """Dispatch immutable runtime events to ordered observer bindings."""

    def __init__(self, config: ObservabilityConfig | None = None) -> None:
        """Initialize a bus with no external side effects."""

        self.config = config or ObservabilityConfig()
        self._status = (
            ObservabilityStatus.HEALTHY
            if any(
                binding.payload_mode is not PayloadMode.DISABLED
                for binding in self.config.observers
            )
            else ObservabilityStatus.DISABLED
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._seen: set[str] = set()
        self._diagnostics: list[RuntimeDiagnostic] = []
        self._failure_index: dict[tuple[int, str | None], RuntimeDiagnostic] = {}
        self._closed = False

    @property
    def status(self) -> ObservabilityStatus:
        """Return the current aggregate observer health."""

        return self._status

    @property
    def diagnostics(self) -> tuple[RuntimeDiagnostic, ...]:
        """Return a stable snapshot of observability diagnostics."""

        return tuple(self._diagnostics)

    async def emit(self, event: RuntimeEvent) -> RuntimeEvent:
        """Dispatch one event and return a terminal result enriched with diagnostics."""

        if self._closed:
            return event
        key = event.invocation_id or f"runtime:{event.runtime!s}"
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                event_key = f"{key}:{event.event_id}"
                if event_key in self._seen:
                    return event
                self._seen.add(event_key)
                strict_failure: ObservabilityError | None = None
                for binding in self.config.observers:
                    mode = (
                        binding.payload_mode
                        if isinstance(binding.payload_mode, PayloadMode)
                        else PayloadMode(binding.payload_mode)
                    )
                    if mode is PayloadMode.DISABLED:
                        continue
                    projected = _project_event(event, mode)
                    try:
                        await asyncio.wait_for(
                            binding.observer.on_event(projected),
                            timeout=self.config.dispatch_timeout_seconds,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        diagnostic = self._record_failure(
                            binding, _FailureKind.DISPATCH, exc, event
                        )
                        strict_failure = ObservabilityError(
                            "Observability dispatch failed",
                            details={
                                "observer": type(binding.observer).__name__,
                                "code": diagnostic.code,
                            },
                        )
                if strict_failure is not None and self.config.strict:
                    raise strict_failure
                return self._enrich_terminal(event)
            finally:
                if event.kind in _TERMINAL_KINDS:
                    self._release(key)

    async def flush(self) -> None:
        """Flush active observers, isolating failures unless strict mode is enabled."""

        await self._lifecycle(_FailureKind.FLUSH, "flush")

    async def close(self) -> None:
        """Flush and close observers exactly once."""

        if self._closed:
            return
        flush_error: ObservabilityError | None = None
        try:
            await self.flush()
        except ObservabilityError as exc:
            flush_error = exc
        close_error: ObservabilityError | None = None
        try:
            await self._lifecycle(_FailureKind.CLOSE, "close")
        except ObservabilityError as exc:
            close_error = exc
        finally:
            self._closed = True
        if self.config.strict:
            if close_error is not None:
                raise close_error
            if flush_error is not None:
                raise flush_error

    async def _lifecycle(self, kind: _FailureKind, method: str) -> None:
        """Run one observer lifecycle method in registration order."""

        strict_failure: ObservabilityError | None = None
        for binding in self.config.observers:
            if binding.payload_mode is PayloadMode.DISABLED:
                continue
            try:
                callback = getattr(binding.observer, method)
                await asyncio.wait_for(callback(), timeout=self.config.shutdown_timeout_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                diagnostic = self._record_failure(binding, kind, exc, None)
                strict_failure = ObservabilityError(
                    f"Observability {method} failed",
                    details={"observer": type(binding.observer).__name__, "code": diagnostic.code},
                )
        if strict_failure is not None and self.config.strict:
            raise strict_failure

    def _record_failure(
        self,
        binding: ObserverBinding,
        kind: _FailureKind,
        exc: Exception,
        event: RuntimeEvent | None,
    ) -> RuntimeDiagnostic:
        """Record one safe observer failure and mark the bus degraded."""

        self._status = ObservabilityStatus.DEGRADED
        invocation = event.invocation_id if event is not None else None
        failure_key = (
            id(binding.observer),
            invocation if kind is _FailureKind.DISPATCH else kind.value,
        )
        if failure_key in self._failure_index:
            return self._failure_index[failure_key]
        code = f"observability.{kind.value}_failed"
        diagnostic = RuntimeDiagnostic(
            code=code,
            message=f"{type(binding.observer).__name__} {kind.value} failed",
            severity=DiagnosticSeverity.WARNING,
            details={
                "observer": type(binding.observer).__name__,
                "exception_type": type(exc).__name__,
                "invocation_id": invocation,
            },
        )
        self._diagnostics.append(diagnostic)
        self._failure_index[failure_key] = diagnostic
        record_failure = getattr(binding.observer, "record_failure", None)
        if record_failure is not None:
            with suppress(Exception):
                record_failure(type(binding.observer).__name__)
        return diagnostic

    def _enrich_terminal(self, event: RuntimeEvent) -> RuntimeEvent:
        """Attach current health and new diagnostics to a terminal result."""

        if event.result is None:
            return event
        status = self._status
        diagnostics = event.result.diagnostics
        scoped = tuple(
            item
            for item in self._diagnostics
            if item.details.get("invocation_id") in {None, event.invocation_id}
        )
        if scoped:
            existing = {(item.code, item.details.get("invocation_id")) for item in diagnostics}
            diagnostics = diagnostics + tuple(
                item
                for item in scoped
                if (item.code, item.details.get("invocation_id")) not in existing
            )
        result = replace(
            event.result,
            diagnostics=diagnostics,
            observability_status=status,
        )
        return replace(event, result=result)

    def _release(self, key: str) -> None:
        """Release per-invocation state after a terminal event."""

        self._locks.pop(key, None)


def _project_event(event: RuntimeEvent, mode: PayloadMode) -> RuntimeEvent:
    """Return a safe event projection for one observer payload mode."""

    metadata_dict = dict(event.metadata)
    provider = getattr(event.runtime, "provider", None)
    runtime_name = provider if isinstance(provider, str) else _safe_runtime_name(event.runtime)
    metadata_dict.setdefault("proteo.runtime", runtime_name)
    if isinstance(provider, str):
        metadata_dict.setdefault("runtime.provider", provider)
        version = getattr(event.runtime, "metadata", {}).get("version")
        if version is not None:
            metadata_dict.setdefault("runtime.version", version)
    for key, value in {
        "proteo.invocation_id": event.invocation_id,
        "proteo.turn_id": event.turn_id,
        "proteo.session_id": _session_correlation_id(event.session_id),
    }.items():
        if value is not None:
            metadata_dict.setdefault(key, value)
    if event.result is not None:
        metadata_dict.setdefault("proteo.model", event.result.model)
        metadata_dict.setdefault("proteo.profile", event.result.profile)
        metadata_dict.setdefault("proteo.reasoning_effort", event.result.reasoning_effort)
        metadata_dict.setdefault("proteo.latency_ms", event.result.usage.duration_ms)
        metadata_dict.setdefault("proteo.retry_count", event.result.usage.retry_count)
        metadata_dict.setdefault("input_tokens", event.result.usage.input_tokens)
        metadata_dict.setdefault("cached_input_tokens", event.result.usage.cached_input_tokens)
        metadata_dict.setdefault("output_tokens", event.result.usage.output_tokens)
        metadata_dict.setdefault("reasoning_tokens", event.result.usage.reasoning_tokens)
        metadata_dict.setdefault("total_tokens", event.result.usage.total_tokens)
        metadata_dict.setdefault("tool_call_count", event.result.usage.tool_call_count)
    usage = metadata_dict.get("usage")
    if isinstance(usage, Mapping):
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "duration_ms",
        ):
            if usage.get(key) is not None:
                metadata_dict.setdefault(key, usage[key])
    metadata = _project_metadata(metadata_dict, mode)
    if mode is PayloadMode.METADATA_ONLY:
        return replace(
            event,
            session_id=_session_correlation_id(event.session_id),
            metadata=metadata,
            payload=MappingProxyType({}),
            result=None,
        )
    payload = _project_value(event.payload, mode, key_hint=None)
    result = event.result
    if result is not None:
        result = replace(
            result,
            raw=None,
            session_id=_session_correlation_id(result.session_id),
            diagnostics=_project_diagnostics(result.diagnostics, mode),
            value=_project_value(result.value, mode, key_hint=None),
        )
    return replace(
        event,
        session_id=_session_correlation_id(event.session_id),
        metadata=metadata,
        payload=payload,
        result=result,
    )


def _session_correlation_id(descriptor: str | None) -> str | None:
    """Return a namespaced one-way correlation value for a session descriptor."""

    if not descriptor:
        return None
    digest = hashlib.sha256(b"proteo-observability-v1\0" + descriptor.encode("utf-8")).hexdigest()
    return f"proteo.session:{digest}"


def _project_metadata(value: Mapping[str, Any], mode: PayloadMode) -> Mapping[str, Any]:
    """Project metadata while removing known content-bearing fields."""

    if mode is PayloadMode.FULL:
        return cast(Mapping[str, Any], _project_value(value, mode, key_hint=None))
    if mode is PayloadMode.REDACTED:
        return _project_redacted_metadata(value)
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).casefold().replace("-", "_")
        if (
            normalized in _SENSITIVE_METADATA_KEYS
            or normalized in _ALWAYS_EXCLUDE_KEYS
            or is_secret_key(str(key))
        ):
            continue
        result[str(key)] = _project_value(item, mode, key_hint=str(key))
    return _freeze_projected(result)


def _project_redacted_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Keep operational metadata readable while redacting content-bearing fields."""

    return _freeze_projected(
        {
            str(key): _project_redacted_metadata_value(item, str(key))
            for key, item in value.items()
            if str(key).casefold().replace("-", "_") not in _ALWAYS_EXCLUDE_KEYS
        }
    )


def _project_diagnostics(
    diagnostics: tuple[RuntimeDiagnostic, ...], mode: PayloadMode
) -> tuple[RuntimeDiagnostic, ...]:
    """Project diagnostic messages and details without retaining exporter causes."""

    projected: list[RuntimeDiagnostic] = []
    for diagnostic in diagnostics:
        details = _project_value(diagnostic.details, mode, key_hint=None)
        projected.append(
            replace(
                diagnostic,
                message=_SECRET_ASSIGNMENT.sub(_redact_secret_match, diagnostic.message),
                details=details,
            )
        )
    return tuple(projected)


def _project_redacted_metadata_value(value: Any, key_hint: str | None) -> Any:
    """Recursively redact only sensitive metadata values and credential-shaped strings."""

    normalized = key_hint.casefold().replace("-", "_") if key_hint is not None else ""
    if key_hint is not None and is_secret_key(key_hint):
        return "[REDACTED]"
    if normalized in _SENSITIVE_METADATA_KEYS:
        return _project_value(value, PayloadMode.REDACTED, key_hint=key_hint)
    if _is_session_key(normalized) and isinstance(value, str):
        return value if value.startswith("proteo.session:") else _session_correlation_id(value)
    if isinstance(value, Mapping):
        return _project_redacted_metadata(value)
    if isinstance(value, (list, tuple)):
        return tuple(_project_redacted_metadata_value(item, None) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(_project_redacted_metadata_value(item, None) for item in value)
    if isinstance(value, str):
        return _SECRET_ASSIGNMENT.sub(_redact_secret_match, value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return f"<{type(value).__name__}>"


def _project_value(value: Any, mode: PayloadMode, key_hint: str | None) -> Any:
    """Recursively project JSON-like data without invoking arbitrary repr methods."""

    if key_hint is not None and is_secret_key(key_hint):
        return "[REDACTED]"
    normalized_key = key_hint.casefold().replace("-", "_") if key_hint is not None else ""
    if _is_session_key(normalized_key) and isinstance(value, str):
        if value.startswith("proteo.session:"):
            return value
        return _session_correlation_id(value)
    if isinstance(value, BaseModel):
        try:
            dumped = value.model_dump(mode="python")
        except Exception:  # noqa: BLE001
            return f"<{type(value).__name__}>"
        return _project_value(dumped, mode, key_hint=None)
    if isinstance(value, Mapping):
        return _freeze_projected(
            {
                str(key): _project_value(item, mode, str(key))
                for key, item in value.items()
                if str(key).casefold().replace("-", "_") not in _ALWAYS_EXCLUDE_KEYS
                and (
                    mode is not PayloadMode.METADATA_ONLY
                    or str(key).casefold().replace("-", "_") not in _SENSITIVE_METADATA_KEYS
                )
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_project_value(item, mode, key_hint=None) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(_project_value(item, mode, key_hint=None) for item in value)
    if isinstance(value, str):
        if mode is PayloadMode.REDACTED:
            return "[REDACTED]"
        return _SECRET_ASSIGNMENT.sub(_redact_secret_match, value)
    if value is None or isinstance(value, (bool, int, float)):
        if mode is PayloadMode.REDACTED and value is not None:
            return f"<{type(value).__name__}>"
        return value
    return f"<{type(value).__name__}>"


def _redact_secret_match(match: re.Match[str]) -> str:
    """Replace a credential-shaped token while retaining its safe prefix."""

    first, second = match.group(1), match.group(2)
    if first is not None:
        return f"{first}[REDACTED]"
    if second is not None:
        return f"{second}[REDACTED]"
    return "[REDACTED]"


def _is_session_key(normalized_key: str) -> bool:
    """Identify session descriptor fields that must be one-way correlated."""

    return normalized_key == "session_id" or normalized_key.endswith("_session_id")


def _safe_runtime_name(runtime: RuntimeIdentity | str) -> str:
    """Return a bounded runtime label without serializing arbitrary objects."""

    if (
        isinstance(runtime, str)
        and len(runtime) <= 64
        and re.fullmatch(r"[A-Za-z0-9_.-]+", runtime)
    ):
        return runtime
    return "unknown"


def _freeze_projected(value: Mapping[str, Any]) -> Mapping[str, Any]:
    """Freeze a projected mapping for observer consumers."""

    return MappingProxyType(dict(value))
