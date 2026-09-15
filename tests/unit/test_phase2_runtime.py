"""Phase 2 configuration, structured output, context, and migration tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel
from test_codex_provider import FakeSDK, FakeTurn, install_sdk

from proteo_runtime.config import RuntimeConfigV1, load_runtime_config, validate_config
from proteo_runtime.config import loader as config_loader
from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.errors import (
    CancellationError,
    CapabilityError,
    ConfigurationError,
    ContextPolicyError,
    RuntimeTimeoutError,
    SessionBusyError,
    SessionNotFoundError,
    StructuredOutputError,
)
from proteo_runtime.core.events import RuntimeEventKind
from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import InvocationConfig, StructuredOutputPolicy
from proteo_runtime.core.session_codec import SessionCodec
from proteo_runtime.providers.codex import runtime as codex_runtime
from proteo_runtime.testing import FakeRuntime
from proteo_runtime.testing import FakeTurn as FakeRuntimeTurn


class Answer(BaseModel):
    """Small Pydantic schema for structured-output tests."""

    answer: str


def _notifications(value: str, *, turn_id: str = "turn-1") -> tuple[Any, ...]:
    """Build SDK notifications containing one scripted agent message."""

    item = SimpleNamespace(type="agentMessage", text=value)
    turn = SimpleNamespace(id=turn_id, status="completed", items=[item], duration_ms=3)
    usage = SimpleNamespace(
        last=SimpleNamespace(inputTokens=2, outputTokens=2, totalTokens=4),
        model_context_window=100,
    )
    notification = SimpleNamespace
    return (
        notification(method="item/agentMessage/delta", payload=SimpleNamespace(delta=value)),
        notification(method="item/completed", payload=SimpleNamespace(item=item)),
        notification(
            method="thread/tokenUsage/updated", payload=SimpleNamespace(token_usage=usage)
        ),
        notification(method="turn/completed", payload=SimpleNamespace(turn=turn)),
    )


def _config_payload() -> dict[str, Any]:
    """Return a compact configuration with one custom persistent profile."""

    mappings = {
        "low": {"model": "gpt-5.6-luna", "reasoning_effort": "low"},
        "medium": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
        "high": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
        "ultra": {"model": "gpt-5.6-sol", "reasoning_effort": "ultra"},
    }
    return {
        "schema_version": 1,
        "runtime": "codex",
        "profiles": {"brain": mappings, "session": mappings, "hybrid": mappings},
        "profile_specs": {
            "hybrid": {
                "lifecycle": "persistent",
                "context_policy": "hybrid",
                "security_policy": "isolated",
                "host_tools": "disabled",
            }
        },
    }


def test_config_sources_precedence_and_no_implicit_cwd(tmp_path: Any, monkeypatch: Any) -> None:
    """Explicit sources override environment and packaged defaults deterministically."""

    env_path = tmp_path / "env.json"
    explicit_path = tmp_path / "explicit.json"
    env_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "codex",
                "profiles": {"brain": {"medium": {"model": "env", "reasoning_effort": "medium"}}},
            }
        ),
        encoding="utf-8",
    )
    explicit_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "codex",
                "profiles": {
                    "brain": {"medium": {"model": "explicit", "reasoning_effort": "medium"}}
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PROTEO_RUNTIME_CONFIG", str(env_path))
    assert load_runtime_config().lookup("brain", "medium").model == "env"
    assert (
        load_runtime_config(config_path=explicit_path).lookup("brain", "medium").model == "explicit"
    )
    typed = RuntimeConfigV1.model_validate(
        {
            "schema_version": 1,
            "runtime": "codex",
            "profiles": {"brain": {"medium": {"model": "typed", "reasoning_effort": "medium"}}},
        }
    )
    assert (
        load_runtime_config(config_path=explicit_path, config=typed).lookup("brain", "medium").model
        == "typed"
    )
    monkeypatch.delenv("PROTEO_RUNTIME_CONFIG")
    monkeypatch.chdir(tmp_path)
    assert load_runtime_config().lookup("brain", "medium").model == "gpt-5.6-terra"
    with pytest.raises(ConfigurationError):
        load_runtime_config(config_path=tmp_path / "broken.json")
    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_runtime_config(config_path=malformed)
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_runtime_config(config_path=malformed)


def test_custom_profile_validation_and_capability_rejection() -> None:
    """Custom profiles are explicit and deferred capabilities fail before provider use."""

    config = validate_config(_config_payload())
    assert config.profile_spec("hybrid").context.value == "hybrid"
    with pytest.raises(ConfigurationError):
        validate_config({**_config_payload(), "runtime": "unsupported"})
    with pytest.raises(ConfigurationError):
        validate_config({**_config_payload(), "profiles": {}})
    with pytest.raises(ConfigurationError):
        validate_config(
            {
                **_config_payload(),
                "profile_specs": {"missing": _config_payload()["profile_specs"]["hybrid"]},
            }
        )
    with pytest.raises(ConfigurationError):
        validate_config(
            {
                **_config_payload(),
                "profile_specs": {
                    "hybrid": {
                        "lifecycle": "persistent",
                        "context_policy": "external",
                        "security_policy": "isolated",
                        "host_tools": "disabled",
                    }
                },
            }
        )
    for spec in (
        {
            "lifecycle": "persistent",
            "context_policy": "external",
            "security_policy": "isolated",
            "host_tools": "disabled",
        },
        {
            "lifecycle": "ephemeral",
            "context_policy": "hybrid",
            "security_policy": "isolated",
            "host_tools": "disabled",
        },
        {
            "lifecycle": "explicit",
            "context_policy": "external",
            "security_policy": "isolated",
            "host_tools": "disabled",
        },
    ):
        with pytest.raises(ConfigurationError):
            validate_config(
                {
                    **_config_payload(),
                    "profile_specs": {"hybrid": spec},
                }
            )
    with pytest.raises(ConfigurationError):
        validate_config(
            {
                **_config_payload(),
                "profile_specs": {
                    "brain": {
                        "lifecycle": "ephemeral",
                        "context_policy": "external",
                        "security_policy": "isolated",
                        "host_tools": "disabled",
                    }
                },
            }
        )


def test_packaged_defaults_fail_closed_when_resource_is_invalid(monkeypatch: Any) -> None:
    """Packaged default parser maps malformed resources to ConfigurationError."""

    class Resource:
        """Minimal importlib resource double."""

        def joinpath(self, *parts: str) -> Resource:
            """Return itself for nested resource lookups."""

            del parts
            return self

        def read_text(self, *, encoding: str) -> str:
            """Return invalid default content."""

            del encoding
            return "[]"

    monkeypatch.setattr(config_loader, "files", lambda package: Resource())
    with pytest.raises(ConfigurationError):
        config_loader._packaged_defaults()


@pytest.mark.asyncio
async def test_codex_mapping_and_structured_retry_buffering(monkeypatch: Any) -> None:
    """Structured output validates locally, retries once, and hides partial JSON."""

    sdk = FakeSDK(
        turns=[
            FakeTurn(notifications=_notifications('{"wrong": true}', turn_id="turn-1")),
            FakeTurn(notifications=_notifications('{"answer": "ok"}', turn_id="turn-2")),
        ]
    )
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = (await runtime.brain(level="medium")).with_structured_output(Answer)
    events = [event async for event in model.astream("return JSON")]
    terminal = events[-1]
    assert terminal.kind is RuntimeEventKind.INVOCATION_COMPLETED
    assert terminal.result is not None
    result = terminal.result
    assert isinstance(result.value, Answer)
    assert result.value.answer == "ok"
    assert result.usage.retry_count == 1
    assert RuntimeEventKind.VALIDATION_FAILED in [event.kind for event in events]
    assert RuntimeEventKind.RETRY_SCHEDULED in [event.kind for event in events]
    assert not any(event.kind is RuntimeEventKind.OUTPUT_TEXT_DELTA for event in events)
    assert [event.sequence for event in events] == list(range(len(events)))
    assert sdk.turn_calls[0][1]["output_schema"]["title"] == "Answer"
    assert sdk.turn_calls[1][1]["output_schema"]["title"] == "Answer"
    await runtime.close()


@pytest.mark.asyncio
async def test_structured_schema_errors_and_raw_opt_in(monkeypatch: Any) -> None:
    """Exhausted validation reports bounded paths and redacted raw output only on opt-in."""

    invalid = '{"token":"secret", "wrong": true}'
    sdk = FakeSDK(
        turns=[
            FakeTurn(notifications=_notifications(invalid)),
            FakeTurn(notifications=_notifications(invalid)),
        ]
    )
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = (await runtime.brain()).with_structured_output(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
            "additionalProperties": False,
        },
        policy=StructuredOutputPolicy(max_attempts=2),
    )
    with pytest.raises(StructuredOutputError) as error:
        await model.ainvoke("return JSON", include_raw=True)
    assert error.value.attempts == 2
    assert "secret" not in str(error.value.raw)
    assert error.value.validation_paths
    await runtime.close()


@pytest.mark.asyncio
async def test_structured_timeout_cancellation_and_redaction_paths(monkeypatch: Any) -> None:
    """Structured timeout/cancellation interrupts active work and sanitizes non-JSON raw text."""

    sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05) for _ in range(3)])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = (await runtime.brain()).with_structured_output(Answer)
    with pytest.raises(RuntimeTimeoutError):
        await model.ainvoke("slow", config=InvocationConfig(timeout_seconds=0.001))
    task = asyncio.create_task(model.ainvoke("cancel"))
    await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(CancellationError):
        await task
    from proteo_runtime.providers.codex._structured import _redact_mapping, _redact_raw

    assert "[REDACTED]" in _redact_raw("token=secret")
    assert (
        _redact_mapping({"nested": {"password": "secret"}, "items": [{"token": "x"}]})["nested"][
            "password"
        ]
        == "[REDACTED]"
    )
    await runtime.close()


def test_structured_schema_validation_rejects_bad_inputs() -> None:
    """Structured schema adapters reject unsupported kinds and malformed meta-schemas."""

    runtime = codex_runtime.CodexRuntime()
    model = runtime.model(profile="brain")
    with pytest.raises(CapabilityError):
        model.with_structured_output(cast(Any, bool))
    with pytest.raises(CapabilityError):
        model.with_structured_output({"type": "not-a-json-schema-type"})
    with pytest.raises(ValueError):
        StructuredOutputPolicy(max_attempts=0)


@pytest.mark.asyncio
async def test_migration_failures_are_non_destructive(monkeypatch: Any) -> None:
    """Migration rejects permission changes, active turns, and provider failures safely."""

    sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    session = await runtime.session()
    with pytest.raises(CapabilityError):
        await runtime.migrate_session(session.id, profile="session", security_policy="native")
    task = asyncio.create_task(session.ainvoke("slow"))
    await asyncio.sleep(0.001)
    with pytest.raises(SessionBusyError):
        await runtime.migrate_session(session.id, profile="session", security_policy="isolated")
    task.cancel()
    with pytest.raises(CancellationError):
        await task
    await runtime.close()


@pytest.mark.asyncio
async def test_hybrid_context_and_same_thread_migration(monkeypatch: Any) -> None:
    """Hybrid context accepts current system/user input and migration preserves the thread."""

    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime(config=validate_config(_config_payload()))
    await runtime.start()
    session = await runtime.session()
    with pytest.raises(ContextPolicyError):
        await session.ainvoke(
            RuntimeInput((RuntimeMessage("assistant", (TextContent("replay"),)),))
        )
    hybrid = await runtime.migrate_session(session.id, profile="hybrid", security_policy="isolated")
    assert hybrid.id != session.id
    assert (
        SessionCodec.decode(hybrid.id).provider_session_id
        == SessionCodec.decode(session.id).provider_session_id
    )
    assert sdk.resume_calls[-1][0] == "thread-1"
    with pytest.raises(SessionNotFoundError):
        await session.ainvoke("stale")
    await hybrid.ainvoke(
        RuntimeInput(
            (
                RuntimeMessage("system", (TextContent("be concise"),)),
                RuntimeMessage("user", (TextContent("hello"),)),
            )
        )
    )
    assert "[system]" in sdk.turn_calls[-1][0][0]
    assert any(event.kind is RuntimeEventKind.SESSION_MIGRATED for event in runtime.events)
    await runtime.close()


@pytest.mark.asyncio
async def test_codex_resume_new_state_and_provider_migration_failure(monkeypatch: Any) -> None:
    """Resume can rebuild local state and provider migration failures map safely."""

    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    session = await runtime.session()
    descriptor = session.id
    runtime._sessions.clear()
    rebuilt = await runtime.resume_session(descriptor)
    assert rebuilt.id == descriptor
    sdk.missing_resume = True
    with pytest.raises(SessionNotFoundError):
        await runtime.migrate_session(descriptor, profile="session", security_policy="isolated")
    await runtime.close()


@pytest.mark.asyncio
async def test_fake_structured_facade_supports_pydantic_retry() -> None:
    """The deterministic fake mirrors structured retry and typed result behavior."""

    runtime = FakeRuntime(
        turns=[FakeRuntimeTurn(value="not-json"), FakeRuntimeTurn(value='{"answer": "fake"}')]
    )
    model = runtime.model(profile="brain").with_structured_output(Answer)
    events = [event async for event in model.astream("input")]
    assert events[-1].result is not None
    assert events[-1].result.value.answer == "fake"
    assert any(event.kind is RuntimeEventKind.RETRY_SCHEDULED for event in events)


@pytest.mark.asyncio
async def test_fake_text_stream_and_json_schema_exhaustion() -> None:
    """Fakes expose ordinary deltas and JSON Schema exhaustion paths."""

    runtime = FakeRuntime(turns=[FakeRuntimeTurn(value="hello")])
    events = [event async for event in runtime.model(profile="brain").astream("input")]
    assert any(event.kind is RuntimeEventKind.OUTPUT_TEXT_DELTA for event in events)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["answer"],
    }
    limited = (
        FakeRuntime(turns=[FakeRuntimeTurn(value="bad"), FakeRuntimeTurn(value="still bad")])
        .model(profile="brain")
        .with_structured_output(schema)
    )
    with pytest.raises(StructuredOutputError):
        await limited.ainvoke("input", include_raw=True)
    disabled = (
        FakeRuntime(capabilities=RuntimeCapabilities(structured_output=False))
        .model(profile="brain")
        .with_structured_output(Answer)
    )
    with pytest.raises(CapabilityError):
        await disabled.effective_capabilities()


@pytest.mark.asyncio
async def test_codex_profile_capabilities_and_session_overrides(monkeypatch: Any) -> None:
    """Deferred profiles reject before thread creation and session bindings stay frozen."""

    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    with pytest.raises(CapabilityError):
        await runtime.model(profile="controlled_agent").ainvoke("tools")
    deferred = runtime.model(profile="controlled_agent").with_structured_output(Answer)
    with pytest.raises(CapabilityError):
        await deferred.effective_capabilities()
    assert not sdk.start_calls
    session = await runtime.session(config=InvocationConfig(include_raw=True))
    with pytest.raises(CapabilityError):
        await session.ainvoke("override", config=InvocationConfig(model="gpt-5.6-luna"))
    await session.close()
    await runtime.close()


@pytest.mark.asyncio
async def test_codex_resolution_error_paths_and_stream_timeout(monkeypatch: Any) -> None:
    """Resolver rejects missing catalog entries and streaming timeout is normalized."""

    sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    assert runtime._resolve_effort(None, "gpt-5.6-terra") == "medium"
    assert (
        runtime._resolve_effort(InvocationConfig(reasoning_effort="low"), "gpt-5.6-terra") == "low"
    )
    with pytest.raises(CapabilityError):
        runtime._resolve_effort(InvocationConfig(reasoning_effort="high"), "gpt-5.6-terra")
    with pytest.raises(CapabilityError):
        runtime._resolve_binding("brain", "low", InvocationConfig(model="missing"))
    with pytest.raises(RuntimeTimeoutError):
        _ = [
            event
            async for event in (await runtime.brain()).astream(
                "slow", config=InvocationConfig(timeout_seconds=0.001)
            )
        ]
    await runtime.close()
