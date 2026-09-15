"""Public, provider-neutral runtime errors with safe diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .types import freeze_mapping


class AgentRuntimeError(Exception):
    """Base error carrying a stable code and sanitized diagnostic details."""

    default_code = "runtime_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        runtime: str | None = None,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initialize an error without retaining credential-shaped values."""

        self.code, self.runtime, self.retryable = code or self.default_code, runtime, retryable
        try:
            self.details = freeze_mapping(details)
        except ValueError:
            self.details = freeze_mapping({"redacted": "unsafe diagnostic details"})
        super().__init__(message)


class AuthenticationError(AgentRuntimeError):
    """Indicate missing or invalid provider authentication."""

    default_code = "authentication_error"


class RuntimeUnavailableError(AgentRuntimeError):
    """Indicate that a provider runtime is unavailable."""

    default_code = "runtime_unavailable"


class CapabilityError(AgentRuntimeError):
    """Indicate that a requested capability is unsupported."""

    default_code = "capability_error"


class ConfigurationError(AgentRuntimeError):
    """Indicate invalid configuration at a known JSON path."""

    default_code = "configuration_error"

    def __init__(self, message: str, *, path: str | None = None, **kwargs: Any) -> None:
        """Initialize a configuration error with optional path metadata."""

        details = dict(kwargs.pop("details", {}) or {})
        if path:
            details["path"] = path
            if path not in message:
                message = f"{message} ({path})"
        super().__init__(message, details=details, **kwargs)
        self.path = path


class StructuredOutputError(AgentRuntimeError):
    """Indicate structured-output validation failure."""

    default_code = "structured_output_error"

    def __init__(
        self,
        message: str,
        *,
        attempts: int = 0,
        validation_paths: tuple[str, ...] = (),
        raw: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize safe validation metadata and optional explicitly requested raw output."""

        self.attempts = attempts
        self.validation_paths = tuple(validation_paths)
        self.raw = raw
        details = dict(kwargs.pop("details", {}) or {})
        details.update({"attempts": attempts, "validation_paths": self.validation_paths})
        super().__init__(message, details=details, **kwargs)


class ToolDeniedError(AgentRuntimeError):
    """Indicate that a requested tool was denied by policy."""

    default_code = "tool_denied"


class ToolExecutionError(AgentRuntimeError):
    """Indicate a tool execution failure."""

    default_code = "tool_execution_error"


class ContextLimitError(AgentRuntimeError):
    """Indicate that context exceeds a runtime limit."""

    default_code = "context_limit_error"


class ContextPolicyError(AgentRuntimeError):
    """Indicate an invalid context policy."""

    default_code = "context_policy_error"


class RuntimeTimeoutError(AgentRuntimeError):
    """Indicate a runtime timeout."""

    default_code = "runtime_timeout"


class InterruptedError(AgentRuntimeError):
    """Indicate an explicit interruption."""

    default_code = "interrupted"


class CancellationError(AgentRuntimeError):
    """Indicate cancellation of an in-flight operation."""

    default_code = "cancelled"


class RetryExhaustedError(AgentRuntimeError):
    """Indicate that retry attempts were exhausted."""

    default_code = "retry_exhausted"


class SecurityPolicyError(AgentRuntimeError):
    """Indicate a security-policy violation."""

    default_code = "security_policy_error"


class SessionBusyError(AgentRuntimeError):
    """Indicate that a session already has an active turn."""

    default_code = "session_busy"


class SessionMismatchError(AgentRuntimeError):
    """Indicate an incompatible or malformed session descriptor."""

    default_code = "session_mismatch"


class SessionNotFoundError(AgentRuntimeError):
    """Indicate that a session identifier is unknown."""

    default_code = "session_not_found"


class ObservabilityError(AgentRuntimeError):
    """Indicate a non-fatal observability failure."""

    default_code = "observability_error"


class TransportError(AgentRuntimeError):
    """Indicate a provider transport failure."""

    default_code = "transport_error"


RuntimeError = AgentRuntimeError
