"""Runtime protocol conformance tests."""

from typing import cast

import pytest

from proteo_runtime import Runtime, RuntimeModel, RuntimeSession
from proteo_runtime.testing import FakeRuntime


def test_fake_objects_satisfy_runtime_protocols() -> None:
    """Fake runtime objects expose the documented protocol members."""

    runtime = FakeRuntime()
    assert isinstance(cast(object, runtime), Runtime)
    assert isinstance(cast(object, runtime.model(profile="brain")), RuntimeModel)


@pytest.mark.asyncio
async def test_session_protocol_is_async_first() -> None:
    """A created fake session satisfies the session protocol."""

    session = await FakeRuntime().session()
    assert isinstance(cast(object, session), RuntimeSession)
    await session.close()
