"""Private compatibility bridge for Codex App Server dynamic tools.

Nothing in this module is part of the provider-neutral API.  It is intentionally
small and defensive because the pinned SDK exposes the dynamic-tool wire types
before exposing a stable high-level helper.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from proteo_runtime.core.errors import CapabilityError
from proteo_runtime.tools import ToolExecutor, ToolRequest, ToolSnapshot


@dataclass(frozen=True, slots=True)
class DynamicToolsCompatibility:
    """Result of a side-effect-free SDK compatibility probe."""

    supported: bool
    reason: str = ""


def probe_dynamic_tools() -> DynamicToolsCompatibility:
    """Check only local SDK symbols needed by the experimental bridge."""

    try:
        from openai_codex import AsyncCodex, AsyncThread
        from openai_codex.client import CodexClient, CodexConfig
        from openai_codex.generated.v2_all import DynamicToolSpec
    except (ImportError, AttributeError) as exc:
        return DynamicToolsCompatibility(
            False, f"missing SDK dynamic-tools symbols: {type(exc).__name__}"
        )
    required = (
        hasattr(AsyncCodex, "_ensure_initialized"),
        hasattr(AsyncThread, "__init__"),
        hasattr(CodexClient, "initialize"),
        "approval_handler" in inspect.signature(CodexClient).parameters,
        hasattr(CodexConfig, "experimental_api"),
        DynamicToolSpec is not None,
    )
    if not all(required):
        return DynamicToolsCompatibility(False, "pinned SDK lacks the private bridge hooks")
    return DynamicToolsCompatibility(True)


def require_dynamic_tools() -> None:
    """Raise before inference when the pinned SDK cannot support the bridge."""

    result = probe_dynamic_tools()
    if not result.supported:
        raise CapabilityError(f"Codex dynamic tools are unavailable: {result.reason}")


def dynamic_tool_specs(snapshot: ToolSnapshot) -> tuple[dict[str, Any], ...]:
    """Serialize a neutral snapshot into App Server dynamic tool specifications."""

    require_dynamic_tools()
    specs: list[dict[str, Any]] = []
    for definition in snapshot.definitions():
        provider_definition = definition.as_provider_dict()
        specs.append(
            {
                "type": "function",
                "name": provider_definition["name"],
                "description": provider_definition["description"],
                "inputSchema": provider_definition["inputSchema"],
            }
        )
    return tuple(specs)


def _thread_id(response: Any) -> str:
    """Extract a thread id from a generated response or test double."""

    thread = getattr(response, "thread", response)
    return str(getattr(thread, "id", getattr(thread, "thread_id", "")))


async def start_thread(sdk: Any, *, dynamic_tools: ToolSnapshot, **params: Any) -> Any:
    """Start a thread through the private raw SDK call with dynamic tools."""

    require_dynamic_tools()
    await sdk._ensure_initialized()
    raw = {key: value for key, value in params.items() if value is not None}
    raw["dynamicTools"] = list(dynamic_tool_specs(dynamic_tools))
    response = await sdk._client.thread_start(raw)
    from openai_codex import AsyncThread

    return AsyncThread(sdk, _thread_id(response))


async def resume_thread(
    sdk: Any, thread_id: str, *, dynamic_tools: ToolSnapshot, **params: Any
) -> Any:
    """Resume a thread through the private raw SDK call with a fresh snapshot."""

    require_dynamic_tools()
    await sdk._ensure_initialized()
    raw = {key: value for key, value in params.items() if value is not None}
    raw["dynamicTools"] = list(dynamic_tool_specs(dynamic_tools))
    response = await sdk._client.thread_resume(thread_id, raw)
    from openai_codex import AsyncThread

    return AsyncThread(sdk, _thread_id(response))


class CodexToolBridge:
    """Adapt synchronous SDK server requests to an asynchronous ToolExecutor."""

    def __init__(
        self, executor: ToolExecutor, loop: asyncio.AbstractEventLoop | None = None
    ) -> None:
        """Capture the host loop used to await tool calls."""

        self.executor = executor
        self.loop = loop or asyncio.get_running_loop()

    def __call__(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Handle exactly one `item/tool/call` request and fail closed otherwise."""

        if method != "item/tool/call" or not isinstance(params, Mapping):
            return {"error": {"code": "tool_denied", "message": "unsupported tool request"}}
        invocation_id = str(
            params.get(
                "invocationId",
                params.get("invocation_id", params.get("turnId", params.get("threadId", ""))),
            )
        )
        call_id = str(
            params.get("callId", params.get("call_id", params.get("itemId", params.get("id", ""))))
        )
        name = str(params.get("name", params.get("tool", params.get("toolName", ""))))
        arguments = params.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = None
        if not invocation_id or not call_id or not name or not isinstance(arguments, Mapping):
            return {"error": {"code": "tool_execution_error", "message": "invalid tool request"}}
        request = ToolRequest(
            invocation_id,
            call_id,
            name,
            arguments,
            session_id=_optional_string(params.get("threadId", params.get("thread_id"))),
            turn_id=_optional_string(params.get("turnId", params.get("turn_id"))),
        )
        future = asyncio.run_coroutine_threadsafe(self.executor.execute(request), self.loop)
        try:
            result = future.result(timeout=self.executor.timeout_seconds + 1)
        except Exception:
            future.cancel()
            return {"error": {"code": "tool_execution_error", "message": "tool execution failed"}}
        payload = {"success": result.success, "output": result.as_provider_value()}
        if result.error_code:
            payload["errorCode"] = result.error_code
        return {"contentItems": [{"type": "inputText", "text": json.dumps(payload)}]}


def install_bridge(sdk: Any, bridge: CodexToolBridge) -> None:
    """Install a deny-by-default bridge before SDK initialization starts."""

    require_dynamic_tools()
    client = getattr(sdk, "_client", None)
    sync_client = getattr(client, "_sync", None)
    if sync_client is None or not hasattr(sync_client, "_approval_handler"):
        raise CapabilityError("Codex SDK does not expose its request handler hook")

    def handler(method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Route dynamic calls and reject every native approval request."""

        if method == "item/tool/call":
            return bridge(method, params)
        return {"decision": "decline", "error": "host-managed tools only"}

    sync_client._approval_handler = handler


def _optional_string(value: Any) -> str | None:
    """Normalize optional protocol identifiers without retaining objects."""

    return str(value) if isinstance(value, str) and value else None


__all__ = [
    "CodexToolBridge",
    "DynamicToolsCompatibility",
    "dynamic_tool_specs",
    "install_bridge",
    "probe_dynamic_tools",
    "require_dynamic_tools",
    "resume_thread",
    "start_thread",
]
