"""Opt-in real Codex smoke tests.

These tests are intentionally skipped unless the caller explicitly enables the
subscription-backed integration suite.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from proteo_runtime.core.model import RuntimeResult

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PROTEO_CODEX_INTEGRATION") != "1", reason="Codex integration is opt-in"
    ),
]

LUNA_MODEL = "gpt-5.6-luna"
LUNA_LEVEL = "low"


def _assert_luna(result: RuntimeResult[Any]) -> None:
    """Assert that a live inference used the authorized Luna/low configuration."""

    assert result.model == LUNA_MODEL
    assert result.reasoning_effort == LUNA_LEVEL


@pytest.mark.asyncio
async def test_codex_catalog_and_brain_smoke() -> None:
    """Verify catalog and brain invocation against an already managed login."""

    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        assert await runtime.models()
        result = await (await runtime.brain(level=LUNA_LEVEL)).ainvoke("Reply with one word.")
        _assert_luna(result)
        assert result.output


@pytest.mark.asyncio
async def test_codex_configured_mapping_catalog() -> None:
    """Verify every configured model/effort mapping against one live catalog."""

    from proteo_runtime.providers.codex import CodexRuntime

    expected = {
        "gpt-5.6-luna": {"low"},
        "gpt-5.6-terra": {"medium"},
        "gpt-5.6-sol": {"high", "ultra"},
    }
    async with CodexRuntime() as runtime:
        models = {model.id: model for model in await runtime.models()}
    for model_id, efforts in expected.items():
        assert model_id in models
        assert efforts <= set(models[model_id].supported_reasoning_efforts)


@pytest.mark.asyncio
async def test_codex_session_lifecycle_smoke() -> None:
    """Verify create, resume, archive, and delete with explicit opt-in."""

    from proteo_runtime.providers.codex import CodexRuntime

    async with CodexRuntime() as runtime:
        session = await runtime.session(level=LUNA_LEVEL)
        descriptor = session.descriptor
        result = await session.ainvoke("Reply with one word.")
        _assert_luna(result)
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
        events = [
            event
            async for event in (await runtime.brain(level=LUNA_LEVEL)).astream(
                "Reply with one word."
            )
        ]
        assert any(event.kind is RuntimeEventKind.OUTPUT_TEXT_DELTA for event in events)
        terminal = events[-1]
        assert terminal.kind is RuntimeEventKind.INVOCATION_COMPLETED
        assert terminal.result is not None
        assert terminal.result.output
        _assert_luna(terminal.result)


@pytest.mark.asyncio
async def test_codex_phase2_structured_and_same_thread_migration() -> None:
    """Verify structured host validation and disposable same-thread migration."""

    from pydantic import BaseModel

    from proteo_runtime.core.errors import SessionNotFoundError
    from proteo_runtime.core.events import RuntimeEventKind
    from proteo_runtime.providers.codex import CodexRuntime

    class DecisionModel(BaseModel):
        """Structured integration response."""

        decision: str

    async with CodexRuntime() as runtime:
        structured = (await runtime.brain(level=LUNA_LEVEL)).with_structured_output(DecisionModel)
        result = await structured.ainvoke(
            'Return exactly JSON matching {"decision":"yes"} and no markdown.'
        )
        assert result.value.decision
        _assert_luna(result)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"decision": {"type": "string"}},
            "required": ["decision"],
            "additionalProperties": False,
        }
        events = [
            event
            async for event in (await runtime.brain(level=LUNA_LEVEL))
            .with_structured_output(schema)
            .astream('Return exactly JSON matching {"decision":"yes"} and no markdown.')
        ]
        assert events[-1].kind is RuntimeEventKind.INVOCATION_COMPLETED
        assert events[-1].result is not None
        _assert_luna(events[-1].result)
        session = await runtime.session(level=LUNA_LEVEL)
        session_result = await session.ainvoke("Reply with one word.")
        _assert_luna(session_result)
        migrated = await runtime.migrate_session(
            session.id, profile="session", level="low", security_policy="isolated"
        )
        assert migrated.id != session.id
        with pytest.raises(SessionNotFoundError):
            await session.ainvoke("stale")
        await migrated.delete()
