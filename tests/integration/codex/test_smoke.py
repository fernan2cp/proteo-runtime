"""Opt-in real Codex smoke tests.

These tests are intentionally skipped unless the caller explicitly enables the
subscription-backed integration suite.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_INTEGRATION") != "1", reason="Codex integration is opt-in"
    ),
]


@pytest.mark.asyncio
async def test_codex_catalog_and_brain_smoke() -> None:
    """Verify catalog and brain invocation against an already managed login."""

    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        assert await runtime.models()
        result = await (await runtime.brain()).ainvoke("Reply with one word.")
        assert result.output


@pytest.mark.asyncio
async def test_codex_session_lifecycle_smoke() -> None:
    """Verify create, resume, archive, and delete with explicit opt-in."""

    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        session = await runtime.session()
        descriptor = session.descriptor
        await session.ainvoke("Reply with one word.")
        await session.close()
        resumed = await runtime.resume_session(descriptor)
        await resumed.archive()
        await resumed.delete()


@pytest.mark.asyncio
async def test_codex_streaming_smoke() -> None:
    """Verify normalized deltas and terminal result against Codex."""

    from proteo_runtime.core.events import RuntimeEventKind
    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        events = [event async for event in (await runtime.brain()).astream("Reply with one word.")]
        assert any(event.kind is RuntimeEventKind.OUTPUT_TEXT_DELTA for event in events)
        terminal = events[-1]
        assert terminal.kind is RuntimeEventKind.INVOCATION_COMPLETED
        assert terminal.result is not None
        assert terminal.result.output
