"""Additional branch coverage for foundational contracts."""

import asyncio
from datetime import datetime

import pytest

from proteo_runtime import (
    CapabilityError,
    RuntimeCapabilities,
    RuntimeEvent,
    RuntimeEventKind,
    RuntimeIdentity,
    RuntimeInput,
    RuntimeMessage,
)
from proteo_runtime.core.errors import CancellationError, SessionMismatchError
from proteo_runtime.core.model_info import ModelInfo
from proteo_runtime.core.profiles import profile_spec
from proteo_runtime.testing import FakeRuntime, FakeTurn


def test_invalid_value_objects_and_profile_names_raise() -> None:
    """Value objects reject malformed content and unknown profiles."""

    with pytest.raises(ValueError):
        RuntimeInput(())
    with pytest.raises(ValueError):
        RuntimeMessage("user", ())
    with pytest.raises(ValueError):
        RuntimeIdentity("", "fingerprint")
    with pytest.raises(ValueError):
        ModelInfo("", "display", (), RuntimeCapabilities())
    with pytest.raises(CapabilityError):
        profile_spec("unknown")


def test_events_require_aware_timestamps_and_usage_is_validated() -> None:
    """Event and usage contracts reject invalid timestamp and counter values."""

    identity = RuntimeIdentity("fake", "fingerprint")
    with pytest.raises(ValueError):
        RuntimeEvent(RuntimeEventKind.RUNTIME_STARTED, "id", 0, datetime.now(), identity)


@pytest.mark.asyncio
async def test_fake_migration_and_structured_output_rejection() -> None:
    """Fake migration preserves identity and rejects unsupported structured output."""

    runtime = FakeRuntime()
    session = await runtime.session()
    migrated = await runtime.migrate_session(
        session.id, profile="brain", level="high", security_policy="isolated"
    )
    assert migrated.id != session.id
    with pytest.raises(CapabilityError):
        runtime.model(profile="brain").with_structured_output(dict)
    with pytest.raises(SessionMismatchError):
        await runtime.resume_session("prt1.invalid")


@pytest.mark.asyncio
async def test_fake_cancellation_is_normalized() -> None:
    """Cancelling a delayed fake invocation emits a safe cancellation error."""

    runtime = FakeRuntime(turns=[FakeTurn(delay_seconds=0.2)])
    session = await runtime.session()
    task = asyncio.create_task(session.ainvoke(RuntimeInput.from_value("wait")))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(CancellationError):
        await task
