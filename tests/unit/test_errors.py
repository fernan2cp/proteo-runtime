"""Error hierarchy and redaction tests."""

import pytest

from proteo_runtime import AgentRuntimeError, ConfigurationError, SessionBusyError
from proteo_runtime.core import errors


def test_all_public_errors_extend_agent_runtime_error() -> None:
    """Every documented R-021 error is a public base error subclass."""

    names = [
        "AuthenticationError",
        "RuntimeUnavailableError",
        "CapabilityError",
        "ConfigurationError",
        "StructuredOutputError",
        "ToolDeniedError",
        "ToolExecutionError",
        "ContextLimitError",
        "ContextPolicyError",
        "RuntimeTimeoutError",
        "InterruptedError",
        "CancellationError",
        "RetryExhaustedError",
        "SecurityPolicyError",
        "SessionBusyError",
        "SessionMismatchError",
        "SessionNotFoundError",
        "ObservabilityError",
    ]
    assert all(issubclass(getattr(errors, name), AgentRuntimeError) for name in names)


def test_error_details_are_redacted_and_paths_are_preserved() -> None:
    """Unsafe details are replaced and configuration paths remain inspectable."""

    error = AgentRuntimeError("safe", details={"token": "hidden"})
    assert "token" not in error.details
    config = ConfigurationError("missing", path="profiles.brain.low")
    assert config.path == "profiles.brain.low"
    with pytest.raises(SessionBusyError):
        raise SessionBusyError("busy", retryable=True)
