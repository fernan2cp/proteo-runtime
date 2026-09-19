"""Quota-safe tests for the Codex provider boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from openai_codex.generated.v2_all import (
    CodexErrorInfo,
    ResponseStreamDisconnected,
    ResponseStreamDisconnectedCodexErrorInfo,
)

from proteo_runtime.config import validate_config
from proteo_runtime.core.errors import (
    AuthenticationError,
    CancellationError,
    CapabilityError,
    ContextPolicyError,
    InterruptedError,
    RuntimeTimeoutError,
    RuntimeUnavailableError,
    SessionBusyError,
    SessionMismatchError,
    SessionNotFoundError,
    StructuredOutputError,
    TransportError,
)
from proteo_runtime.core.events import RuntimeEventKind
from proteo_runtime.core.input import RuntimeInput, RuntimeMessage, TextContent
from proteo_runtime.core.model import InvocationConfig
from proteo_runtime.providers.codex import runtime as codex_runtime
from proteo_runtime.providers.codex._mapping import (
    account_value,
    fingerprint,
    identity_metadata,
    safe_raw,
    serialize_input,
)
from proteo_runtime.providers.codex._runner import usage_from_sdk


@dataclass
class FakeAccount:
    """Account double with the shape accepted by the adapter."""

    type: str = "chatgpt"
    email: str | None = "user@example.test"
    plan_type: str = "plus"


@dataclass
class FakeModel:
    """Visible SDK model double."""

    model: str = "gpt-5.6-terra"
    display_name: str = "Test"
    is_default: bool = True
    hidden: bool = False
    description: str = "test model"
    supported_reasoning_efforts: tuple[str, ...] = ("low", "medium")


@dataclass
class FakeNotification:
    """SDK notification double."""

    method: str
    payload: Any


class FakeTurn:
    """Async SDK turn double with configurable notifications."""

    def __init__(
        self,
        notifications: tuple[FakeNotification, ...] | None = None,
        *,
        delay_seconds: float = 0.0,
        turn_id: str = "turn-1",
    ) -> None:
        """Store scripted stream behavior."""

        self.id = turn_id
        self.notifications = notifications or _notifications()
        self.delay_seconds = delay_seconds
        self.interrupted = False

    async def stream(self) -> AsyncIterator[FakeNotification]:
        """Yield the scripted notification stream."""

        for notification in self.notifications:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            yield notification

    async def interrupt(self) -> None:
        """Record interruption requests."""

        self.interrupted = True


class FakeThread:
    """Async SDK thread double."""

    def __init__(self, sdk: FakeSDK, thread_id: str = "thread-1") -> None:
        """Bind the thread to its owning SDK double."""

        self.sdk = sdk
        self.id = thread_id

    async def turn(self, *args: Any, **kwargs: Any) -> FakeTurn:
        """Create the next scripted turn."""

        self.sdk.turn_calls.append((args, kwargs))
        return self.sdk.next_turn()


class FakeSDK:
    """Minimal AsyncCodex-compatible SDK double."""

    def __init__(
        self,
        *,
        account: Any | None = None,
        models: list[Any] | None = None,
        turns: list[FakeTurn] | None = None,
        missing_resume: bool = False,
    ) -> None:
        """Initialize account, catalog, turns, and call records."""

        self.account_value = account or FakeAccount()
        self.model_values = models or [
            FakeModel(model="gpt-5.6-terra", is_default=True),
            FakeModel(
                model="gpt-5.6-luna",
                is_default=False,
                supported_reasoning_efforts=("low", "medium", "high", "ultra"),
            ),
            FakeModel(
                model="gpt-5.6-sol",
                is_default=False,
                supported_reasoning_efforts=("low", "medium", "high", "ultra"),
            ),
        ]
        self.turn_values = list(turns or [])
        self.missing_resume = missing_resume
        self.turn_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.start_calls: list[dict[str, Any]] = []
        self.resume_calls: list[tuple[str, dict[str, Any]]] = []
        self.archive_calls: list[str] = []
        self.delete_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.close_count = 0
        self._raw_started: list[dict[str, Any]] = []
        self._raw_resumed: list[tuple[str, dict[str, Any]]] = []

        async def _raw_thread_start(params: dict[str, Any]) -> Any:
            self._raw_started.append(params)
            thread_id = f"thread-{len(self._raw_started)}"
            return SimpleNamespace(thread=SimpleNamespace(id=thread_id))

        async def _raw_thread_resume(thread_id: str, params: dict[str, Any]) -> Any:
            self._raw_resumed.append((thread_id, params))
            return SimpleNamespace(thread=SimpleNamespace(id=thread_id))

        self._client = SimpleNamespace(
            request=self.request,
            thread_start=_raw_thread_start,
            thread_resume=_raw_thread_resume,
            _sync=SimpleNamespace(_approval_handler=None),
        )

    async def _ensure_initialized(self) -> None:
        """Simulate App Server initialization."""

    async def account(self, refresh_token: bool = False) -> Any:
        """Return the configured managed account."""

        del refresh_token
        return self.account_value

    async def models(self, include_hidden: bool = False) -> Any:
        """Return the configured catalog."""

        del include_hidden
        return SimpleNamespace(data=self.model_values)

    async def thread_start(self, **kwargs: Any) -> FakeThread:
        """Create and record a fake thread."""

        self.start_calls.append(kwargs)
        return FakeThread(self, f"thread-{len(self.start_calls)}")

    async def thread_resume(self, thread_id: str, **kwargs: Any) -> FakeThread:
        """Resume a fake thread or simulate a missing provider thread."""

        self.resume_calls.append((thread_id, kwargs))
        if self.missing_resume:
            raise LookupError("missing")
        return FakeThread(self, thread_id)

    async def thread_archive(self, thread_id: str) -> None:
        """Record an archive operation."""

        self.archive_calls.append(thread_id)

    async def request(self, *args: Any, **kwargs: Any) -> None:
        """Record the private typed deletion request."""

        self.delete_calls.append((args, kwargs))

    async def close(self) -> None:
        """Record SDK closure."""

        self.close_count += 1

    def next_turn(self) -> FakeTurn:
        """Return the next scripted turn."""

        if self.turn_values:
            return self.turn_values.pop(0)
        return FakeTurn()


def _notifications(status: str = "completed") -> tuple[FakeNotification, ...]:
    """Build a realistic Codex notification sequence."""

    item = SimpleNamespace(type="agentMessage", text="ok")
    turn = SimpleNamespace(
        id="turn-1",
        status=status,
        items=[item],
        duration_ms=17,
    )
    usage = SimpleNamespace(
        last=SimpleNamespace(
            inputTokens=3,
            outputTokens=2,
            totalTokens=5,
            cachedInputTokens=1,
            reasoningOutputTokens=1,
            cacheWriteInputTokens=4,
        ),
        model_context_window=100,
    )
    return (
        FakeNotification(
            "item/agentMessage/delta",
            SimpleNamespace(delta="ok", item_id="item-1", turn_id="turn-1"),
        ),
        FakeNotification("item/completed", SimpleNamespace(item=item)),
        FakeNotification("thread/tokenUsage/updated", SimpleNamespace(token_usage=usage)),
        FakeNotification("turn/completed", SimpleNamespace(turn=turn)),
    )


def _config_for_model(model: str) -> Any:
    """Build a complete v1 config pointing every built-in profile at one model."""

    levels = {
        level: {"model": model, "reasoning_effort": level}
        for level in ("low", "medium", "high", "ultra")
    }
    return validate_config(
        {
            "schema_version": 1,
            "runtime": "codex",
            "profiles": {
                "brain": levels,
                "structured": levels,
                "session": levels,
            },
        }
    )


def install_sdk(monkeypatch: pytest.MonkeyPatch, sdk: FakeSDK) -> None:
    """Install one SDK double through the provider factory."""

    monkeypatch.setattr(codex_runtime, "_create_sdk", lambda *args, **kwargs: sdk)


@pytest.mark.asyncio
async def test_lifecycle_catalog_brain_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise lifecycle, catalog, identity, workspace, and brain mapping."""

    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    await runtime.start()
    assert (await runtime.models())[0].id == "gpt-5.6-terra"
    model = await runtime.brain(InvocationConfig(reasoning_effort="low"))
    result = await model.ainvoke(
        RuntimeInput(
            (
                RuntimeMessage("system", (TextContent("Be concise."),)),
                RuntimeMessage("user", (TextContent("hello"),)),
            )
        )
    )
    assert result.output == "ok"
    assert result.runtime.provider == "codex"
    assert sdk.start_calls[0]["ephemeral"] is True
    assert sdk.start_calls[0]["sandbox"].value == "read-only"
    assert sdk.start_calls[0]["approval_mode"].value == "deny_all"
    await runtime.close()
    await runtime.close()
    assert sdk.close_count == 1


@pytest.mark.asyncio
async def test_context_manager_restart_and_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise context management, restart, capabilities, and model facade."""

    first = FakeSDK()
    second = FakeSDK()
    values = iter([first, second])
    monkeypatch.setattr(codex_runtime, "_create_sdk", lambda: next(values))
    async with codex_runtime.CodexRuntime() as runtime:
        assert (await runtime.capabilities()).persistent_sessions
        assert await runtime.effective_capabilities()
        model = runtime.model(profile="brain", level="medium")
        assert await model.effective_capabilities()
    await runtime.start()
    await runtime.close()
    assert first.close_count == 1
    assert second.close_count == 1


@pytest.mark.asyncio
async def test_authentication_and_catalog_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject non-ChatGPT identity and unknown explicit catalog models."""

    bad = FakeSDK(account=FakeAccount(type="apiKey"))
    install_sdk(monkeypatch, bad)
    with pytest.raises(AuthenticationError):
        await codex_runtime.CodexRuntime().start()
    install_sdk(monkeypatch, FakeSDK())
    with pytest.raises(CapabilityError):
        await codex_runtime.CodexRuntime(default_model="missing").start()
    models = [
        FakeModel(model="one", is_default=False),
        FakeModel(model="two", is_default=False),
    ]
    install_sdk(monkeypatch, FakeSDK(models=models))
    with pytest.raises(CapabilityError, match="profiles.brain.low"):
        await codex_runtime.CodexRuntime().start()


@pytest.mark.asyncio
async def test_hidden_models_and_effort_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exclude hidden catalog entries and reject unsupported efforts."""

    models = [
        FakeModel(supported_reasoning_efforts=("low", "medium")),
        FakeModel(
            model="gpt-5.6-luna",
            is_default=False,
            supported_reasoning_efforts=("low", "medium", "high", "ultra"),
        ),
        FakeModel(
            model="gpt-5.6-sol",
            is_default=False,
            supported_reasoning_efforts=("low", "medium", "high", "ultra"),
        ),
        FakeModel(model="hidden", hidden=True, is_default=False),
    ]
    sdk = FakeSDK(models=models)
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    assert [model.id for model in await runtime.models()] == [
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
    ]
    model = await runtime.brain(InvocationConfig(model="gpt-5.6-terra", reasoning_effort="high"))
    with pytest.raises(CapabilityError):
        await model.ainvoke("bad effort")


@pytest.mark.asyncio
async def test_structured_migration_and_profiles_are_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate structured schemas and reject invalid migration/profile requests."""

    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    structured = (await runtime.brain()).with_structured_output({"type": "object"})
    with pytest.raises(StructuredOutputError):
        await structured.ainvoke("invalid")
    with pytest.raises(SessionMismatchError):
        await runtime.migrate_session("unused", profile="session", security_policy="isolated")
    with pytest.raises(CapabilityError):
        await runtime.session(profile="brain")
    assert len(sdk.start_calls) == 1


@pytest.mark.asyncio
async def test_streaming_result_usage_and_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise shared streaming, terminal result parity, usage, and redaction."""

    sdk = FakeSDK(turns=[FakeTurn()])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = await runtime.brain(InvocationConfig(include_raw=True))
    events = [event async for event in model.astream("hello")]
    terminal = events[-1]
    assert terminal.kind is RuntimeEventKind.INVOCATION_COMPLETED
    assert terminal.result is not None
    assert terminal.result.output == "ok"
    assert terminal.result.usage.total_tokens == 5
    assert terminal.result.usage.duration_ms == 17
    assert terminal.result.raw is not None
    assert all(not hasattr(event.metadata.get("usage"), "stream") for event in events)
    await runtime.close()


@pytest.mark.asyncio
async def test_timeout_and_cancellation_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interrupt active turns for timeout and caller cancellation."""

    sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05), FakeTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = await runtime.brain(InvocationConfig(timeout_seconds=0.001))
    with pytest.raises(RuntimeTimeoutError):
        await model.ainvoke("slow")
    model = await runtime.brain()
    task = asyncio.create_task(model.ainvoke("cancel"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(CancellationError):
        await task
    await runtime.close()


@pytest.mark.asyncio
async def test_session_resume_concurrency_context_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise persistent lifecycle, policy validation, lock, resume, and delete."""

    sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05), FakeTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    session = await runtime.session()
    assert session.id.startswith("prt1.")
    assert sdk.start_calls[-1]["ephemeral"] is False
    with pytest.raises(ContextPolicyError):
        await session.ainvoke(
            RuntimeInput((RuntimeMessage("assistant", (TextContent("replay"),)),))
        )
    task = asyncio.create_task(session.ainvoke("first"))
    await asyncio.sleep(0)
    with pytest.raises(SessionBusyError):
        await session.ainvoke("second")
    await task
    resumed = await runtime.resume_session(session.descriptor)
    assert resumed.id == session.id
    await session.close()
    await resumed.archive()
    await resumed.close()
    assert any(event.kind is RuntimeEventKind.SESSION_CLOSED for event in runtime.events)
    await resumed.delete()
    assert sdk.archive_calls
    assert sdk.delete_calls
    with pytest.raises(SessionNotFoundError):
        await resumed.ainvoke("gone")


@pytest.mark.asyncio
async def test_resume_mismatch_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject malformed, mismatched, and missing session descriptors."""

    sdk = FakeSDK()
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    with pytest.raises(SessionMismatchError):
        await runtime.resume_session("prt1.invalid")
    session = await runtime.session()
    descriptor = session.descriptor
    other = codex_runtime.CodexRuntime()
    install_sdk(monkeypatch, FakeSDK(account=FakeAccount(email="other@example.test")))
    await other.start()
    with pytest.raises(SessionMismatchError):
        await other.resume_session(descriptor)
    await runtime.close()
    missing = FakeSDK(missing_resume=True)
    install_sdk(monkeypatch, missing)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    with pytest.raises(SessionNotFoundError):
        await runtime.resume_session(descriptor)


def test_mapping_helpers_redact_and_serialize() -> None:
    """Cover deterministic input, identity precision, and safe raw mappings."""

    assert account_value(SimpleNamespace(root=FakeAccount())) is not None
    digest, metadata = identity_metadata(
        SimpleNamespace(account=SimpleNamespace(root=FakeAccount()))
    )
    assert len(digest) == 64
    assert "user@example.test" not in str(metadata)
    degraded, degraded_metadata = identity_metadata(FakeAccount(email=None))
    assert degraded != digest
    assert degraded_metadata["identity_precision"] == "degraded"
    prompt, instructions = serialize_input(
        RuntimeInput(
            (
                RuntimeMessage("system", (TextContent("rules"),)),
                RuntimeMessage("user", (TextContent("hello"),)),
            )
        )
    )
    assert "[user]" in prompt and instructions == "rules"
    with pytest.raises(ValueError):
        serialize_input(RuntimeInput((RuntimeMessage("system", (TextContent("rules"),)),)))
    assert fingerprint({"b": 2, "a": 1}) == fingerprint({"a": 1, "b": 2})
    assert safe_raw({"status": "ok", "email": "secret"})["status"] == "ok"


def test_usage_aliases_and_private_error_mapping() -> None:
    """Cover usage aliases and sanitized SDK error classification."""

    usage = SimpleNamespace(
        last=SimpleNamespace(
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
            cached_input_tokens=0,
            reasoning_tokens=1,
        )
    )
    assert usage_from_sdk(usage).total_tokens == 3
    for name, expected in [
        ("FakeAuthError", AuthenticationError),
        ("FakeTimeoutError", RuntimeTimeoutError),
        ("FakeCancelledError", CancellationError),
        ("FakeNotFoundError", SessionNotFoundError),
        ("FakeInterruptError", InterruptedError),
        ("FakeCapabilityError", CapabilityError),
        ("FakeTransportError", TransportError),
    ]:
        error = codex_runtime._map_sdk_error(type(name, (Exception,), {})(), "test")
        assert isinstance(error, expected)


class ErrorSDK(FakeSDK):
    """SDK double with injectable operation failures."""

    def __init__(self, *, archive_error: bool = False, delete_error: bool = False) -> None:
        """Configure failing operations."""

        super().__init__()
        self.archive_error = archive_error
        self.delete_error = delete_error

    async def thread_archive(self, thread_id: str) -> None:
        """Raise when archive is configured to fail."""

        if self.archive_error:
            raise RuntimeError("archive failed")
        await super().thread_archive(thread_id)

    async def request(self, *args: Any, **kwargs: Any) -> None:
        """Raise when deletion is configured to fail."""

        if self.delete_error:
            raise RuntimeError("delete failed")
        await super().request(*args, **kwargs)


class ErrorTurn(FakeTurn):
    """Turn double whose stream fails at transport level."""

    async def stream(self) -> AsyncIterator[FakeNotification]:
        """Raise a provider stream error."""

        if self.delay_seconds < 0:
            yield FakeNotification("", None)
        raise RuntimeError("stream failed")


class BadInterruptTurn(FakeTurn):
    """Turn double whose interruption request fails."""

    async def interrupt(self) -> None:
        """Raise when interruption cannot be confirmed."""

        raise RuntimeError("interrupt failed")


@pytest.mark.asyncio
async def test_lazy_helpers_and_startup_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover lazy construction, identity guard, fallback IDs, and startup errors."""

    marker = object()
    import openai_codex

    monkeypatch.setattr(openai_codex, "AsyncCodex", lambda: marker)
    assert codex_runtime._create_sdk() is marker
    assert codex_runtime._safe_model_id(SimpleNamespace(id="fallback")) == "fallback"
    runtime = codex_runtime.CodexRuntime()
    with pytest.raises(RuntimeUnavailableError):
        _ = runtime.identity
    broken = BrokenModelsSDK()
    install_sdk(monkeypatch, broken)
    with pytest.raises(TransportError):
        await runtime.start()
    assert broken.close_count == 1
    await runtime._close_sdk(SimpleNamespace())


@pytest.mark.asyncio
async def test_default_resolution_empty_and_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover catalog operation without a default and explicit model selection."""

    no_default = FakeSDK(
        models=[
            FakeModel(model="gpt-5.6-terra", is_default=False),
            FakeModel(
                model="gpt-5.6-luna",
                is_default=False,
                supported_reasoning_efforts=("low", "medium", "high", "ultra"),
            ),
            FakeModel(
                model="gpt-5.6-sol",
                is_default=False,
                supported_reasoning_efforts=("low", "medium", "high", "ultra"),
            ),
        ]
    )
    install_sdk(monkeypatch, no_default)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    assert runtime._selected_model is None
    selected = FakeSDK(
        models=[
            FakeModel(
                model="chosen",
                is_default=False,
                supported_reasoning_efforts=("low", "medium", "high", "ultra"),
            )
        ]
    )
    install_sdk(monkeypatch, selected)
    runtime = codex_runtime.CodexRuntime(default_model="chosen", config=_config_for_model("chosen"))
    await runtime.start()
    assert (await runtime.models())[0].id == "chosen"


@pytest.mark.asyncio
async def test_runner_failed_interrupted_and_fallback_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover failed, interrupted, and missing terminal notification paths."""

    turns = [
        FakeTurn(notifications=_notifications("failed")),
        FakeTurn(notifications=_notifications("interrupted")),
        FakeTurn(
            notifications=(
                FakeNotification("item/agentMessage/delta", SimpleNamespace(delta="fallback")),
            )
        ),
    ]
    sdk = FakeSDK(turns=turns)
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = await runtime.brain()
    failed: list[Any] = []
    with pytest.raises(RuntimeUnavailableError):
        async for event in model.astream("failed"):
            failed.append(event)
    assert any(event.kind is RuntimeEventKind.TURN_FAILED for event in failed)
    interrupted: list[Any] = []
    with pytest.raises(InterruptedError):
        async for event in model.astream("interrupted"):
            interrupted.append(event)
    assert any(event.kind is RuntimeEventKind.TURN_INTERRUPTED for event in interrupted)
    assert any(event.kind is RuntimeEventKind.INTERRUPTED for event in interrupted)
    fallback: list[Any] = []
    with pytest.raises(TransportError):
        async for event in model.astream("fallback"):
            fallback.append(event)
    assert fallback[-1].kind is RuntimeEventKind.INVOCATION_FAILED


@pytest.mark.asyncio
async def test_failed_turn_preserves_safe_provider_error_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve safe provider error codes while redacting sensitive details."""

    notifications = list(_notifications("failed"))
    terminal = notifications[-1].payload.turn
    terminal.error = SimpleNamespace(
        codex_error_info=CodexErrorInfo(
            root=ResponseStreamDisconnectedCodexErrorInfo(
                response_stream_disconnected=ResponseStreamDisconnected(http_status_code=400)
            )
        ),
        message="sensitive provider message",
        additional_details="sensitive additional details",
    )
    sdk = FakeSDK(turns=[FakeTurn(notifications=tuple(notifications))])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = await runtime.brain()
    events: list[Any] = []

    with pytest.raises(RuntimeUnavailableError) as raised:
        async for event in model.astream("failed structured turn"):
            events.append(event)

    failed_events = [
        event
        for event in events
        if event.kind in {RuntimeEventKind.TURN_FAILED, RuntimeEventKind.INVOCATION_FAILED}
    ]
    assert [event.kind for event in failed_events] == [
        RuntimeEventKind.TURN_FAILED,
        RuntimeEventKind.INVOCATION_FAILED,
    ]
    for event in failed_events:
        assert event.metadata["provider_status"] == "failed"
        assert event.metadata["provider_error_code"] == "responseStreamDisconnected"
        assert event.metadata["provider_http_status"] == 400
        assert "sensitive provider message" not in repr(event.metadata)
        assert "sensitive additional details" not in repr(event.metadata)
        assert "sensitive provider message" not in repr(event.payload)
        assert "sensitive additional details" not in repr(event.payload)
    assert raised.value.details["provider_status"] == "failed"
    assert raised.value.details["provider_error_code"] == "responseStreamDisconnected"
    assert raised.value.details["provider_http_status"] == 400
    assert "sensitive provider message" not in repr(raised.value.details)
    assert "sensitive additional details" not in repr(raised.value.details)


@pytest.mark.asyncio
async def test_stream_error_and_session_stream_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Map stream failures and release persistent session locks on timeout."""

    stream_sdk = FakeSDK(turns=[ErrorTurn()])
    install_sdk(monkeypatch, stream_sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    with pytest.raises(TransportError):
        _ = [event async for event in (await runtime.brain()).astream("failure")]
    timeout_sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, timeout_sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    session = await runtime.session()
    with pytest.raises(RuntimeTimeoutError):
        _ = [
            event
            async for event in session.astream(
                "slow", config=InvocationConfig(timeout_seconds=0.001)
            )
        ]
    assert not session._state.lock.locked()


@pytest.mark.asyncio
async def test_session_archive_delete_errors_and_close_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Map archive/delete errors and exercise idempotent close behavior."""

    sdk = ErrorSDK(archive_error=True, delete_error=True)
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    session = await runtime.session()
    with pytest.raises(TransportError):
        await session.archive()
    with pytest.raises(TransportError):
        await session.delete()
    await session.close()
    await session.close()
    assert any(event.kind is RuntimeEventKind.SESSION_CLOSED for event in runtime.events)


@pytest.mark.asyncio
async def test_stream_cancellation_and_runtime_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover stream cancellation and transport invalidation after bad interrupt."""

    sdk = FakeSDK(turns=[FakeTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, sdk)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    model = await runtime.brain()
    task = asyncio.create_task(model.ainvoke("cancel"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(CancellationError):
        await task
    bad = FakeSDK(turns=[BadInterruptTurn(delay_seconds=0.05)])
    install_sdk(monkeypatch, bad)
    runtime = codex_runtime.CodexRuntime()
    await runtime.start()
    with pytest.raises(RuntimeTimeoutError):
        await (await runtime.brain(InvocationConfig(timeout_seconds=0.001))).ainvoke("invalidate")
    assert runtime._closed


class BrokenModelsSDK(FakeSDK):
    """SDK double whose model catalog request fails."""

    async def models(self, include_hidden: bool = False) -> Any:
        """Raise a generic transport failure."""

        del include_hidden
        raise RuntimeError("models failed")
