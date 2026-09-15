"""Contract tests for provider-neutral host-managed tools."""

from __future__ import annotations

import asyncio
import json
import math
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest

from proteo_runtime.config import ModelMapping, ProfileConfig, RuntimeConfigV1
from proteo_runtime.core.capabilities import RuntimeCapabilities
from proteo_runtime.core.context import ContextPolicy
from proteo_runtime.core.errors import (
    CapabilityError,
    RetryExhaustedError,
    ToolDeniedError,
    ToolExecutionError,
)
from proteo_runtime.core.events import RuntimeEventKind
from proteo_runtime.core.profiles import HostToolsMode, LifecycleMode, LogicalLevel, ProfileSpec
from proteo_runtime.core.security import SecurityPolicy
from proteo_runtime.providers.codex.experimental import (
    CodexToolBridge,
    dynamic_tool_specs,
    install_bridge,
    probe_dynamic_tools,
    require_dynamic_tools,
    resume_thread,
    start_thread,
)
from proteo_runtime.providers.codex.runtime import CodexRuntime, _create_sdk
from proteo_runtime.testing.fakes import FakeRuntime
from proteo_runtime.tools import (
    ApprovalDecision,
    ApprovalRequirement,
    SideEffect,
    ToolDefinition,
    ToolExecutor,
    ToolFailurePolicy,
    ToolPermissionPolicy,
    ToolRegistry,
    ToolRequest,
    ToolResult,
    ToolRetryPolicy,
    _schema_for,
    runtime_tool,
)


@runtime_tool(
    name="add_value",
    description="Add two values.",
    permission="math.add",
)
async def add_value(value: int, extra: int = 1) -> int:
    """Add two integers."""

    return value + extra


@runtime_tool(
    name="write_value",
    description="Write a value.",
    permission="data.write",
    side_effect=SideEffect.WRITE,
    approval=ApprovalRequirement.ALWAYS,
)
async def write_value(value: str) -> str:
    """Return the written value."""

    return value


@runtime_tool(
    name="flaky_value",
    description="Fail once then return a value.",
    permission="data.read",
    idempotent=True,
)
async def flaky_value(value: int) -> int:
    """Return a value after a caller-controlled failure."""

    global FLAKY_CALLS
    if FLAKY_CALLS == 0:
        FLAKY_CALLS += 1
        raise RuntimeError("private failure")
    return value


FLAKY_CALLS = 0


@runtime_tool(
    name="slow_value",
    description="Sleep before returning.",
    permission="data.read",
    timeout_seconds=0.01,
)
async def slow_value(value: int) -> int:
    """Sleep long enough to exercise the timeout path."""

    await asyncio.sleep(0.1)
    return value


@runtime_tool(
    name="always_fail",
    description="Always fail for retry tests.",
    permission="data.read",
    idempotent=True,
)
async def always_fail(value: int) -> int:
    """Raise a private exception on every attempt."""

    del value
    raise RuntimeError("private failure")


@runtime_tool(name="bad_output", description="Bad output.", permission="data.read")
async def bad_output(value: int) -> dict[str, str]:
    """Return a value with a deliberately invalid runtime type."""

    return {"value": value}  # type: ignore[dict-item]


def test_registry_snapshots_are_immutable() -> None:
    """A snapshot remains stable when the source registry changes."""

    registry = ToolRegistry()
    registry.register(add_value)
    snapshot = registry.snapshot()
    registry.register(write_value)
    assert [item.name for item in snapshot.definitions()] == ["add_value"]
    assert snapshot.provider_definitions()[0]["name"] == "add_value"


@pytest.mark.asyncio
async def test_executor_validates_permission_and_deduplicates() -> None:
    """Valid calls execute once and duplicate call ids share the result."""

    seen: list[RuntimeEventKind] = []

    async def sink(event: object) -> None:
        """Collect emitted event kinds for the host observer."""

        seen.append(cast(Any, event).kind)

    registry = ToolRegistry()
    registry.register(add_value)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"math.add"})),
        event_sink=sink,
    )
    request = ToolRequest("invocation", "call", "add_value", {"value": 2})
    first, second = await asyncio.gather(executor.execute(request), executor.execute(request))
    assert first is second
    assert first.success is True
    assert first.as_provider_value() == 3
    assert RuntimeEventKind.TOOL_COMPLETED in seen


@pytest.mark.asyncio
async def test_executor_default_policy_returns_sanitized_denial() -> None:
    """A missing approval handler denies side effects without calling the tool."""

    registry = ToolRegistry()
    registry.register(write_value)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"data.write"})),
    )
    result = await executor.execute(
        ToolRequest("invocation", "call", "write_value", {"value": "x"})
    )
    assert result.success is False
    assert result.denied is True
    assert result.error_code == "tool_denied"


@pytest.mark.asyncio
async def test_executor_raises_in_strict_mode() -> None:
    """Strict policy raises a neutral Proteo error for denied calls."""

    registry = ToolRegistry()
    registry.register(add_value)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(),
        failure_policy=ToolFailurePolicy.RAISE,
    )
    with pytest.raises(ToolDeniedError):
        await executor.execute(ToolRequest("invocation", "call", "add_value", {"value": 2}))


@pytest.mark.asyncio
async def test_executor_approval_and_retry_paths() -> None:
    """Approval and bounded idempotent retries produce safe results and events."""

    class Approval:
        """Approve every request in the deterministic test."""

        async def request_approval(self, request: object) -> ApprovalDecision:
            """Approve one request."""

            del request
            return ApprovalDecision.APPROVE

    registry = ToolRegistry()
    registry.register(write_value)
    registry.register(flaky_value)
    registry.register(always_fail)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"data.write", "data.read"})),
        approval_handler=Approval(),
        retry_policy=ToolRetryPolicy(max_attempts=2),
    )
    approved = await executor.execute(ToolRequest("i", "write", "write_value", {"value": "ok"}))
    assert approved.success is True
    global FLAKY_CALLS
    FLAKY_CALLS = 0
    retried = await executor.execute(ToolRequest("i", "flaky", "flaky_value", {"value": 4}))
    assert retried.success is True
    assert retried.attempts == 2
    assert any(event.kind is RuntimeEventKind.TOOL_RETRY_SCHEDULED for event in executor.events)


@pytest.mark.asyncio
async def test_executor_timeout_unknown_invalid_output_and_strict_retry() -> None:
    """Timeout, unknown, invalid arguments, and exhausted retries are sanitized."""

    global FLAKY_CALLS
    registry = ToolRegistry()
    registry.register(add_value)
    registry.register(slow_value)
    registry.register(flaky_value)
    registry.register(always_fail)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"math.add", "data.read"})),
    )
    unknown = await executor.execute(ToolRequest("i", "unknown", "missing", {}))
    invalid = await executor.execute(ToolRequest("i", "invalid", "add_value", {"value": "bad"}))
    timeout = await executor.execute(ToolRequest("i", "timeout", "slow_value", {"value": 1}))
    assert {unknown.error_code, invalid.error_code, timeout.error_code} == {"tool_execution_error"}
    strict = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"data.read"})),
        failure_policy=ToolFailurePolicy.RAISE,
        retry_policy=ToolRetryPolicy(max_attempts=2),
    )
    FLAKY_CALLS = 0
    with pytest.raises(RetryExhaustedError):
        await strict.execute(ToolRequest("strict", "always", "always_fail", {"value": 2}))
    with pytest.raises(ToolExecutionError):
        await strict.execute(ToolRequest("strict", "invalid", "add_value", {"value": "bad"}))


def test_experimental_snapshot_and_probe() -> None:
    """The experimental compatibility probe and provider projection stay local and safe."""

    registry = ToolRegistry()
    registry.register(add_value)
    specs = dynamic_tool_specs(registry.snapshot())
    assert specs[0]["name"] == "add_value"
    assert specs[0]["type"] == "function"
    assert "inputSchema" in specs[0]
    assert isinstance(probe_dynamic_tools().supported, bool)


@pytest.mark.asyncio
async def test_experimental_bridge_rejects_unknown_requests() -> None:
    """The bridge rejects unknown server requests without touching a callable."""

    registry = ToolRegistry()
    registry.register(add_value)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"math.add"})),
    )
    bridge = CodexToolBridge(executor)
    assert bridge("item/started", {})["error"]["code"] == "tool_denied"
    assert (
        bridge("item/tool/call", {"name": "add_value"})["error"]["code"] == "tool_execution_error"
    )


@pytest.mark.asyncio
async def test_experimental_raw_thread_shim_and_bridge_response() -> None:
    """The private shim injects schemas and routes a valid call on the host loop."""

    class RawClient:
        """Capture raw start/resume payloads and expose the approval hook."""

        def __init__(self) -> None:
            self._sync = SimpleNamespace(_approval_handler=None)
            self.started: dict[str, object] | None = None

        async def thread_start(self, params: dict[str, object]) -> object:
            """Return a generated-looking start response."""

            self.started = params
            return SimpleNamespace(thread=SimpleNamespace(id="thread-start"))

        async def thread_resume(self, thread_id: str, params: dict[str, object]) -> object:
            """Return a generated-looking resume response."""

            del params
            return SimpleNamespace(thread=SimpleNamespace(id=thread_id))

    class SDK:
        """Minimal async SDK double for the private shim."""

        def __init__(self) -> None:
            self._client = RawClient()

        async def _ensure_initialized(self) -> None:
            """Pretend the App Server handshake completed."""

    registry = ToolRegistry()
    registry.register(add_value)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"math.add"})),
    )
    sdk = SDK()
    thread = await start_thread(sdk, dynamic_tools=registry.snapshot(), model="model")
    resumed = await resume_thread(sdk, "thread-start", dynamic_tools=registry.snapshot())
    assert thread.id == "thread-start"
    assert resumed.id == "thread-start"
    assert sdk._client.started is not None
    started_payload = cast(dict[str, Any], sdk._client.started)
    assert cast(list[dict[str, Any]], started_payload["dynamicTools"])[0]["name"] == "add_value"
    bridge = CodexToolBridge(executor)
    install_bridge(sdk, bridge)
    response = await asyncio.to_thread(
        sdk._client._sync._approval_handler,
        "item/tool/call",
        {"invocationId": "i", "callId": "c", "name": "add_value", "arguments": {"value": 2}},
    )
    assert "contentItems" in response
    tool_response = await asyncio.to_thread(
        sdk._client._sync._approval_handler,
        "item/tool/call",
        {"invocationId": "i", "callId": "c-tool", "tool": "add_value", "arguments": {"value": 3}},
    )
    assert json.loads(tool_response["contentItems"][0]["text"])["success"] is True
    assert sdk._client._sync._approval_handler("command/exec", {})["decision"] == "decline"
    with pytest.raises(CapabilityError):
        install_bridge(SimpleNamespace(_client=SimpleNamespace(_sync=SimpleNamespace())), bridge)
    invalid = bridge(
        "item/tool/call",
        {
            "invocationId": "i",
            "callId": "c2",
            "name": "add_value",
            "arguments": "{",
        },
    )
    assert invalid["error"]["code"] == "tool_execution_error"
    strict_bridge = CodexToolBridge(ToolExecutor(registry, failure_policy=ToolFailurePolicy.RAISE))
    strict_response = await asyncio.to_thread(
        strict_bridge,
        "item/tool/call",
        {"invocationId": "i", "callId": "strict", "name": "add_value", "arguments": {"value": 2}},
    )
    assert strict_response["error"]["code"] == "tool_execution_error"
    denied_response = await asyncio.to_thread(
        bridge,
        "item/tool/call",
        {"invocationId": "i", "callId": "unknown", "name": "missing", "arguments": {}},
    )
    assert "errorCode" in denied_response["contentItems"][0]["text"]


def test_runtime_tool_rejects_sync_or_untyped_functions() -> None:
    """The decorator rejects signatures that cannot produce safe schemas."""

    with pytest.raises(TypeError):

        @runtime_tool(name="sync", description="bad", permission="bad")  # type: ignore[arg-type]
        def sync(value: int) -> int:
            """Invalid synchronous tool."""

            return value

    with pytest.raises(TypeError):
        _schema_for(Any)
    with pytest.raises(TypeError):
        _schema_for(object())

    with pytest.raises(TypeError):

        @runtime_tool(name="variadic", description="bad", permission="bad")
        async def variadic(*values: int) -> int:
            """Invalid variadic tool."""

            return sum(values)


def test_contract_validation_rejects_unsafe_metadata_and_values() -> None:
    """Public immutable contracts reject malformed schemas and JSON values."""

    with pytest.raises(ValueError):
        ToolDefinition("bad name", "description", {"type": "object"}, {"type": "string"}, "p")
    with pytest.raises(ValueError):
        ToolDefinition("ok", "", {"type": "object"}, {"type": "string"}, "p")
    with pytest.raises(ValueError):
        ToolDefinition("ok", "description", {"type": "not-a-type"}, {"type": "string"}, "p")
    with pytest.raises(ValueError):
        ToolDefinition(
            "ok",
            "description",
            {"type": "object"},
            {"type": "string"},
            "p",
            timeout_seconds=math.inf,
        )
    with pytest.raises(TypeError):
        ToolRequest("i", "c", "tool", {"value": object()})
    with pytest.raises(ValueError):
        ToolRequest("", "c", "tool", {})
    with pytest.raises(ValueError):
        ToolResult("i", "c", "tool", False, attempts=-1)
    with pytest.raises(ValueError):
        ToolRetryPolicy(max_attempts=4)
    with pytest.raises(ValueError):
        ToolPermissionPolicy(frozenset({""}))
    frozen = ToolRequest("i", "c", "tool", {"values": {3, 1}})
    assert tuple(frozen.arguments["values"]) == (1, 3)


def test_registry_rejects_duplicates_and_bad_bindings() -> None:
    """Registry registration never accepts duplicate names or unsafely bound callables."""

    registry = ToolRegistry()
    registry.register(add_value)
    with pytest.raises(ValueError):
        registry.register(add_value)
    with pytest.raises(TypeError):
        registry.register(
            ToolDefinition("direct", "direct", {"type": "object"}, {"type": "integer"}, "p")
        )

    async def direct(value: int) -> int:
        """Return a directly bound value."""

        return value

    definition = ToolDefinition("direct_ok", "direct", {"type": "object"}, {"type": "integer"}, "p")
    assert registry.register(definition, direct).name == "direct_ok"

    async def missing_return(value: int):  # type: ignore[no-untyped-def]
        """Return an untyped value."""

        return value

    with pytest.raises(TypeError):
        registry.register(definition, missing_return)
    assert registry.get("missing") is None
    assert registry.snapshot().get("missing") is None


@pytest.mark.asyncio
async def test_executor_invalid_output_approval_timeout_and_cleanup() -> None:
    """Output validation, invalid approval responses, timeout, and cache cleanup are safe."""

    class InvalidApproval:
        """Return an invalid non-enum decision."""

        async def request_approval(self, request: object) -> str:
            """Return an invalid response."""

            del request
            return "maybe"

    registry = ToolRegistry()
    registry.register(bad_output)
    registry.register(write_value)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"data.read", "data.write"})),
        approval_handler=cast(Any, InvalidApproval()),
        approval_timeout_seconds=0.01,
    )
    output = await executor.execute(ToolRequest("i", "bad", "bad_output", {"value": 1}))
    denied = await executor.execute(ToolRequest("i", "approval", "write_value", {"value": "x"}))
    assert output.error_code == "tool_execution_error"
    assert denied.denied is True
    executor.end_invocation("i")
    again = await executor.execute(ToolRequest("i", "bad", "bad_output", {"value": 1}))
    assert again is not output


def test_decorator_rejects_missing_return_and_argument_annotations() -> None:
    """Decorator schema generation fails closed for incomplete annotations."""

    with pytest.raises(TypeError):

        @runtime_tool(name="missing_return", description="bad", permission="bad")
        async def missing_return(value: int):  # type: ignore[no-untyped-def]
            """Missing return annotation."""

            return value

    with pytest.raises(TypeError):

        @runtime_tool(name="missing_arg", description="bad", permission="bad")
        async def missing_arg(value):  # type: ignore[no-untyped-def]
            """Missing argument annotation."""

            return value


def test_executor_constructor_and_snapshot_inputs_are_checked() -> None:
    """Timeout configuration and direct snapshot construction remain bounded."""

    registry = ToolRegistry()
    registry.register(add_value)
    snapshot = registry.snapshot()
    with pytest.raises(ValueError):
        ToolExecutor(snapshot, timeout_seconds=0)
    with pytest.raises(ValueError):
        ToolExecutor(snapshot, approval_timeout_seconds=math.inf)
    assert ToolExecutor(snapshot).snapshot.definitions()[0].name == "add_value"


def test_probe_reports_missing_sdk_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing provider SDK is reported as an unsupported experimental capability."""

    monkeypatch.setitem(sys.modules, "openai_codex", None)
    result = probe_dynamic_tools()
    assert result.supported is False
    with pytest.raises(CapabilityError):
        require_dynamic_tools()


@pytest.mark.asyncio
async def test_fake_and_codex_tool_bindings_gate_profiles_and_sessions() -> None:
    """Fake and Codex bindings enforce capabilities, snapshots, and custom sessions."""

    registry = ToolRegistry()
    registry.register(add_value)
    capabilities = RuntimeCapabilities(
        structured_output=True,
        ephemeral_sessions=True,
        persistent_sessions=True,
        streaming=True,
        interruption=True,
        host_tools=True,
        sandbox=True,
        usage_reporting=True,
    )
    fake = FakeRuntime(capabilities=capabilities)
    bound = fake.model(profile="controlled_agent").with_tools(registry)
    assert (await bound.effective_capabilities()).host_tools is True
    with pytest.raises(CapabilityError):
        bound.with_structured_output({"type": "string"})
    config = RuntimeConfigV1(
        runtime="fake",
        profiles={
            "custom": {
                LogicalLevel(level): ModelMapping(model="fake", reasoning_effort="medium")
                for level in ("low", "medium", "high", "ultra")
            }
        },
        profile_specs={
            "custom": ProfileConfig(
                lifecycle=LifecycleMode.PERSISTENT,
                context_policy=ContextPolicy.HYBRID,
                security_policy=SecurityPolicy.CONTROLLED_TOOLS,
                host_tools=HostToolsMode.CONTROLLED,
            )
        },
    )
    configured = FakeRuntime(capabilities=capabilities, config=config)
    session = await configured.session("custom", registry=registry)
    await session.close()
    resumed = await configured.resume_session(session.id, registry=registry)
    await resumed.close()
    codex = CodexRuntime(experimental_dynamic_tools=True)
    spec = ProfileSpec(
        LifecycleMode.EPHEMERAL,
        ContextPolicy.EXTERNAL,
        HostToolsMode.CONTROLLED,
        SecurityPolicy.CONTROLLED_TOOLS,
    )
    snapshot, executor = codex._tool_binding(spec, registry, None)
    assert snapshot is not None and executor is not None
    with pytest.raises(CapabilityError):
        CodexRuntime()._tool_binding(spec, registry, None)
    sdk = _create_sdk(experimental_dynamic_tools=True)
    await sdk.close()
