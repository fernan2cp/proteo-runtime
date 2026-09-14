"""Contract tests for immutable provider-neutral values."""

from datetime import UTC, datetime

import pytest

from proteo_runtime import (
    ContextPolicy,
    ExecutionProfile,
    InvocationConfig,
    RuntimeCapabilities,
    RuntimeDiagnostic,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeIdentity,
    RuntimeInput,
    RuntimeMessage,
    RuntimeUsage,
    TextContent,
)
from proteo_runtime.core.diagnostics import DiagnosticSeverity


def test_runtime_input_normalizes_only_strings_and_inputs() -> None:
    """Strings become one user message and arbitrary objects are rejected."""

    value = RuntimeInput.from_value("hello")
    assert value.messages == (RuntimeMessage("user", (TextContent("hello"),)),)
    assert RuntimeInput.from_value(value) is value
    with pytest.raises(TypeError):
        RuntimeInput.from_value(123)  # type: ignore[arg-type]


def test_contracts_are_frozen_and_metadata_is_immutable() -> None:
    """Core values cannot be mutated or retain mutable metadata."""

    usage = RuntimeUsage(total_tokens=3, raw={"nested": [1]})
    with pytest.raises(TypeError):
        usage.raw["x"] = 2
    with pytest.raises(ValueError):
        RuntimeIdentity("fake", "id", metadata={"api_key": "secret"})
    config = InvocationConfig(metadata={"labels": ["test"]})
    with pytest.raises(TypeError):
        config.metadata["labels"] = ()  # type: ignore[index]


def test_profiles_capabilities_and_events_have_stable_vocabulary() -> None:
    """Enums and event correlation fields remain stable and typed."""

    assert ExecutionProfile.BRAIN.value == "brain"
    assert ContextPolicy.HYBRID.value == "hybrid"
    capabilities = RuntimeCapabilities(streaming=True)
    identity = RuntimeIdentity("fake", "fingerprint")
    event = RuntimeEvent(
        RuntimeEventKind.RUNTIME_STARTED,
        "event-1",
        0,
        datetime.now(UTC),
        identity,
    )
    diagnostic = RuntimeDiagnostic("info", "ok", DiagnosticSeverity.INFO)
    assert capabilities.streaming and event.sequence == 0 and diagnostic.code == "info"
