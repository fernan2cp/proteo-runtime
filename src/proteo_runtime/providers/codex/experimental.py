"""Private compatibility bridge for Codex App Server dynamic tools.

Nothing in this module is part of the provider-neutral API.  It is intentionally
small and defensive because the pinned SDK exposes the dynamic-tool wire types
before exposing a stable high-level helper.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
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
    """Check the exact pinned SDK surface needed by the experimental bridge."""

    try:
        from openai_codex import AsyncCodex, AsyncThread
        from openai_codex.client import CodexClient, CodexConfig
        from openai_codex.generated.v2_all import (
            DynamicToolCallThreadItem,
            DynamicToolSpec,
            FunctionDynamicToolSpec,
            InputTextDynamicToolCallOutputContentItem,
        )
    except (ImportError, AttributeError) as exc:
        return DynamicToolsCompatibility(
            False, f"missing SDK dynamic-tools symbols: {type(exc).__name__}"
        )
    try:
        version = importlib.metadata.version("openai-codex")
    except importlib.metadata.PackageNotFoundError:
        return DynamicToolsCompatibility(False, "openai-codex is not installed")
    if version != "0.147.0":
        return DynamicToolsCompatibility(False, f"unsupported openai-codex version: {version}")
    required = (
        hasattr(AsyncCodex, "_ensure_initialized"),
        hasattr(AsyncThread, "__init__"),
        hasattr(CodexClient, "initialize"),
        "approval_handler" in inspect.signature(CodexClient).parameters,
        hasattr(CodexConfig, "experimental_api"),
        set(getattr(FunctionDynamicToolSpec, "model_fields", {})) >= {
            "name",
            "description",
            "input_schema",
            "type",
        },
        set(getattr(DynamicToolCallThreadItem, "model_fields", {})) >= {
            "id",
            "tool",
            "arguments",
            "content_items",
            "success",
        },
        "text" in getattr(InputTextDynamicToolCallOutputContentItem, "model_fields", {}),
        "params" in inspect.signature(CodexClient.thread_start).parameters,
        "params" in inspect.signature(CodexClient.thread_resume).parameters,
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
    sdk: Any, thread_id: str, *, dynamic_tools: ToolSnapshot | None, **params: Any
) -> Any:
    """Resume a thread through the private raw SDK call with a fresh snapshot."""

    require_dynamic_tools()
    await sdk._ensure_initialized()
    raw = {key: value for key, value in params.items() if value is not None}
    raw["dynamicTools"] = list(dynamic_tool_specs(dynamic_tools)) if dynamic_tools else []
    response = await sdk._client.thread_resume(thread_id, raw)
    from openai_codex import AsyncThread

    return AsyncThread(sdk, _thread_id(response))


class CodexToolBridge:
    """Adapt synchronous SDK server requests to an asynchronous ToolExecutor."""

    def __init__(
        self,
        executor: ToolExecutor,
        loop: asyncio.AbstractEventLoop | None = None,
        *,
        invocation_id: str | None = None,
    ) -> None:
        """Capture the host loop used to await tool calls."""

        self.executor = executor
        self.loop = loop or asyncio.get_running_loop()
        self.invocation_id = invocation_id
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self._pending: set[Any] = set()

    def bind(self, *, thread_id: str, turn_id: str) -> None:
        """Bind this bridge to one provider thread and turn."""

        self.thread_id, self.turn_id = thread_id, turn_id

    def unbind(self) -> None:
        """Cancel pending reader-thread waits and remove provider identifiers."""

        for future in tuple(self._pending):
            future.cancel()
        self._pending.clear()
        if self.invocation_id:
            self.executor.end_invocation(self.invocation_id)
        self.thread_id = self.turn_id = None

    def matches(self, params: Mapping[str, Any]) -> bool:
        """Return whether a protocol request belongs to this bridge."""

        thread_id = _optional_string(params.get("threadId", params.get("thread_id")))
        turn_id = _optional_string(params.get("turnId", params.get("turn_id")))
        request_invocation = _optional_string(
            params.get("invocationId", params.get("invocation_id"))
        )
        if request_invocation and self.invocation_id == request_invocation:
            return True
        if self.thread_id and thread_id and self.thread_id != thread_id:
            return False
        if self.turn_id and turn_id and self.turn_id != turn_id:
            return False
        return self.thread_id is None or thread_id == self.thread_id

    def __call__(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Handle exactly one `item/tool/call` request and fail closed otherwise."""

        if method != "item/tool/call" or not isinstance(params, Mapping):
            return _dynamic_response(False, "tool_denied", "unsupported tool request")
        if not self.matches(params):
            return _dynamic_response(False, "tool_denied", "unknown tool request route")
        invocation_id = str(
            params.get(
                "invocationId",
                params.get(
                    "invocation_id",
                    self.invocation_id or params.get("turnId", params.get("threadId", "")),
                ),
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
            return _dynamic_response(False, "tool_execution_error", "invalid tool request")
        try:
            request = ToolRequest(
                invocation_id,
                call_id,
                name,
                arguments,
                session_id=_optional_string(params.get("threadId", params.get("thread_id"))),
                turn_id=_optional_string(params.get("turnId", params.get("turn_id"))),
            )
        except (TypeError, ValueError):
            return _dynamic_response(False, "tool_execution_error", "invalid tool request")
        future = asyncio.run_coroutine_threadsafe(self.executor.execute(request), self.loop)
        self._pending.add(future)
        try:
            result = future.result()
        except Exception:
            future.cancel()
            return _dynamic_response(False, "tool_execution_error", "tool execution failed")
        finally:
            self._pending.discard(future)
        payload = {"success": result.success, "output": result.as_provider_value()}
        if result.error_code:
            payload["errorCode"] = result.error_code
        return {
            "contentItems": [{"type": "inputText", "text": json.dumps(payload)}],
            "success": result.success,
        }


class CodexToolMux:
    """Route private SDK requests to one bridge per active thread and turn."""

    def __init__(self) -> None:
        """Initialize an empty request router."""

        self._routes: dict[tuple[str, str], CodexToolBridge] = {}

    def register(self, bridge: CodexToolBridge, *, thread_id: str, turn_id: str) -> None:
        """Register one active provider route."""

        bridge.bind(thread_id=thread_id, turn_id=turn_id)
        self._routes[(thread_id, turn_id)] = bridge

    def unregister(self, bridge: CodexToolBridge) -> None:
        """Remove a route and cancel all its pending requests."""

        for key, candidate in tuple(self._routes.items()):
            if candidate is bridge:
                self._routes.pop(key, None)
        bridge.unbind()

    def __call__(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Dispatch dynamic calls and decline every native approval request."""

        if method != "item/tool/call":
            return {"decision": "decline", "error": "host-managed tools only"}
        if not isinstance(params, Mapping):
            return _dynamic_response(False, "tool_denied", "invalid tool request")
        thread_id = _optional_string(params.get("threadId", params.get("thread_id")))
        turn_id = _optional_string(params.get("turnId", params.get("turn_id")))
        bridge = self._routes.get((thread_id or "", turn_id or ""))
        if bridge is None:
            invocation_id = _optional_string(
                params.get("invocationId", params.get("invocation_id"))
            )
            bridge = next(
                (
                    candidate
                    for candidate in self._routes.values()
                    if invocation_id and candidate.invocation_id == invocation_id
                ),
                None,
            )
        if bridge is None:
            return _dynamic_response(False, "tool_denied", "unknown tool request route")
        return bridge(method, dict(params))

    def close(self) -> None:
        """Cancel and remove all routes during runtime shutdown."""

        for bridge in tuple(self._routes.values()):
            self.unregister(bridge)


def install_bridge(sdk: Any, bridge: CodexToolBridge) -> CodexToolMux:
    """Install a deny-by-default bridge before SDK initialization starts."""

    require_dynamic_tools()
    client = getattr(sdk, "_client", None)
    sync_client = getattr(client, "_sync", None)
    if sync_client is None or not hasattr(sync_client, "_approval_handler"):
        raise CapabilityError("Codex SDK does not expose its request handler hook")

    current = getattr(sync_client, "_approval_handler", None)
    mux = current if isinstance(current, CodexToolMux) else CodexToolMux()
    sync_client._approval_handler = mux
    return mux


def _dynamic_response(success: bool, code: str, message: str) -> dict[str, Any]:
    """Build a protocol-valid dynamic-tool response for errors and denials."""

    payload = {"success": success, "errorCode": code, "message": message}
    return {
        "contentItems": [{"type": "inputText", "text": json.dumps(payload)}],
        "success": success,
    }


def _optional_string(value: Any) -> str | None:
    """Normalize optional protocol identifiers without retaining objects."""

    return str(value) if isinstance(value, str) and value else None


__all__ = [
    "CodexToolBridge",
    "CodexToolMux",
    "DynamicToolsCompatibility",
    "dynamic_tool_specs",
    "install_bridge",
    "probe_dynamic_tools",
    "require_dynamic_tools",
    "resume_thread",
    "start_thread",
]
