"""Shared Codex turn execution and notification normalization."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from proteo_runtime.core.errors import (
    AgentRuntimeError,
    InterruptedError,
    RuntimeUnavailableError,
    TransportError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.model import RuntimeResult
from proteo_runtime.core.usage import RuntimeUsage

from ._mapping import enum_value, safe_raw


class AsyncTurnHandle(Protocol):
    """Minimal async turn handle implemented by the pinned SDK and doubles."""

    id: str

    def stream(self) -> AsyncIterator[object]:
        """Return the notification stream."""

    async def interrupt(self) -> object:
        """Request interruption."""


def _event(
    kind: RuntimeEventKind,
    *,
    identity: RuntimeIdentity,
    invocation_id: str,
    sequence: int,
    session_id: str | None,
    turn_id: str | None,
    metadata: Mapping[str, Any] | None = None,
    result: RuntimeResult[Any] | None = None,
    payload: Mapping[str, Any] | None = None,
    task_id: str | None = None,
) -> RuntimeEvent:
    """Build one provider-neutral event."""

    return RuntimeEvent(
        kind=kind,
        event_id=f"{invocation_id}:{sequence}",
        sequence=sequence,
        occurred_at=datetime.now(UTC),
        runtime=identity,
        invocation_id=invocation_id,
        session_id=session_id,
        turn_id=turn_id,
        metadata=dict(metadata or {}),
        result=result,
        payload=dict(payload or {}),
        task_id=task_id,
    )


def usage_from_sdk(usage: object, *, duration_ms: float | None = None) -> RuntimeUsage:
    """Normalize the SDK token usage object into the neutral contract."""

    value = getattr(usage, "last", usage)

    def field(name: str, alias: str, default: int | None = None) -> int | None:
        """Read one snake-case or SDK alias field."""
        candidate = getattr(value, name, getattr(value, alias, default))
        return candidate

    raw = {
        "cache_write_input_tokens": field("cache_write_input_tokens", "cacheWriteInputTokens"),
        "model_context_window": getattr(usage, "model_context_window", None),
    }
    raw = {key: item for key, item in raw.items() if item is not None}
    return RuntimeUsage(
        input_tokens=field("input_tokens", "inputTokens"),
        output_tokens=field("output_tokens", "outputTokens"),
        total_tokens=field("total_tokens", "totalTokens"),
        cached_input_tokens=field("cached_input_tokens", "cachedInputTokens"),
        reasoning_tokens=field("reasoning_tokens", "reasoningOutputTokens"),
        duration_ms=duration_ms,
        raw=raw,
    )


def _usage_metadata(usage: object) -> Mapping[str, int | float | None]:
    """Return scalar usage fields safe for event metadata."""

    normalized = usage_from_sdk(usage)
    return {
        "input_tokens": normalized.input_tokens,
        "cached_input_tokens": normalized.cached_input_tokens,
        "output_tokens": normalized.output_tokens,
        "reasoning_tokens": normalized.reasoning_tokens,
        "total_tokens": normalized.total_tokens,
        "duration_ms": normalized.duration_ms,
    }


def _provider_error_metadata(turn: object) -> dict[str, str | int]:
    """Extract allowlisted Codex error classification from a failed turn.

    Provider message text and additional details are deliberately never read.
    """

    turn_error = getattr(turn, "error", None)
    error_info = getattr(turn_error, "codex_error_info", None)
    root = getattr(error_info, "root", error_info)
    stable_codes = {
        "contextWindowExceeded",
        "sessionBudgetExceeded",
        "usageLimitExceeded",
        "serverOverloaded",
        "cyberPolicy",
        "internalServerError",
        "unauthorized",
        "badRequest",
        "threadRollbackFailed",
        "sandboxError",
        "other",
        "httpConnectionFailed",
        "responseStreamConnectionFailed",
        "responseStreamDisconnected",
        "responseTooManyFailedAttempts",
        "activeTurnNotSteerable",
    }
    variant_names = {
        "http_connection_failed": "httpConnectionFailed",
        "response_stream_connection_failed": "responseStreamConnectionFailed",
        "response_stream_disconnected": "responseStreamDisconnected",
        "response_too_many_failed_attempts": "responseTooManyFailedAttempts",
        "active_turn_not_steerable": "activeTurnNotSteerable",
    }
    metadata: dict[str, str | int] = {}

    value = getattr(root, "value", root)
    if isinstance(value, str) and value in stable_codes:
        metadata["provider_error_code"] = value
    else:
        for attr, code in variant_names.items():
            variant = getattr(root, attr, None)
            if variant is None:
                continue
            metadata["provider_error_code"] = code
            status = getattr(variant, "http_status_code", getattr(variant, "httpStatusCode", None))
            if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
                metadata["provider_http_status"] = status
            break

    return metadata


@dataclass
class TurnRun:
    """Collect one SDK turn while exposing one neutral event stream."""

    runtime_name: str
    identity: RuntimeIdentity
    handle: AsyncTurnHandle
    invocation_id: str
    model: str
    profile: str
    effort: str
    session_id: str | None = None
    task_id: str | None = None
    include_raw: bool = False
    context_policy: str | None = None
    security_policy: str | None = None
    invocation_metadata: Mapping[str, Any] = field(default_factory=dict)
    ephemeral: bool = True
    structured_output: bool = False
    provider_thread: Any | None = None
    cleanup: Callable[[], None] | None = None
    event_sink: Callable[[RuntimeEvent], Awaitable[RuntimeEvent]] | None = None
    deltas: list[str] = field(default_factory=list)
    items: list[object] = field(default_factory=list)
    usage: object | None = None
    result: RuntimeResult[str] | None = None
    terminal_status: str | None = None
    terminal_error: AgentRuntimeError | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    _sequence: int = 0

    def _emit(
        self,
        kind: RuntimeEventKind,
        *,
        turn_id: str | None,
        metadata: Mapping[str, Any] | None = None,
        result: RuntimeResult[Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Create the next monotonic event."""

        event = _event(
            kind,
            identity=self.identity,
            invocation_id=self.invocation_id,
            sequence=self._sequence,
            session_id=self.session_id,
            turn_id=turn_id,
            metadata=metadata,
            result=result,
            payload=payload,
            task_id=self.task_id,
        )
        self._sequence += 1
        return event

    async def _publish(self, event: RuntimeEvent) -> RuntimeEvent:
        """Send an event through the runtime bus and retain enriched results."""

        published = await self.event_sink(event) if self.event_sink is not None else event
        if published.result is not None:
            self.result = published.result
        return published

    async def events(self) -> AsyncIterator[RuntimeEvent]:
        """Yield normalized events and attach the terminal result."""

        turn_id = str(getattr(self.handle, "id", ""))
        try:
            yield await self._publish(
                self._emit(
                    RuntimeEventKind.INVOCATION_STARTED,
                    turn_id=turn_id,
                    metadata={
                        **dict(self.invocation_metadata),
                        "model": self.model,
                        "profile": self.profile,
                        "reasoning_effort": self.effort,
                        "context_policy": self.context_policy,
                        "security_policy": self.security_policy,
                        "ephemeral": self.ephemeral,
                        "structured_output": self.structured_output,
                    },
                )
            )
            yield await self._publish(self._emit(RuntimeEventKind.TURN_STARTED, turn_id=turn_id))
            async for notification in self.handle.stream():
                method = str(getattr(notification, "method", ""))
                payload = getattr(notification, "payload", notification)
                if method == "turn/started":
                    started = getattr(payload, "turn", payload)
                    turn_id = str(getattr(started, "id", turn_id))
                elif method == "item/agentMessage/delta":
                    delta = str(getattr(payload, "delta", "") or "")
                    self.deltas.append(delta)
                    yield await self._publish(
                        self._emit(
                            RuntimeEventKind.OUTPUT_TEXT_DELTA,
                            turn_id=turn_id,
                            payload={"text": delta},
                        )
                    )
                elif method == "item/completed":
                    item = getattr(payload, "item", None)
                    if item is not None:
                        self.items.append(item)
                elif method == "thread/tokenUsage/updated":
                    self.usage = getattr(
                        payload, "token_usage", getattr(payload, "tokenUsage", None)
                    )
                    yield await self._publish(
                        self._emit(
                            RuntimeEventKind.TOKEN_USAGE_UPDATED,
                            turn_id=turn_id,
                            metadata={"usage": _usage_metadata(self.usage)},
                        )
                    )
                elif method == "turn/completed":
                    turn = getattr(payload, "turn", payload)
                    if not self.items:
                        self.items.extend(getattr(turn, "items", ()) or ())
                    status = enum_value(getattr(turn, "status", None)) or "completed"
                    self.terminal_status = status
                    failure_metadata: dict[str, str | int] = {
                        "status": status,
                        "provider_status": status,
                    }
                    if status == "interrupted":
                        self.terminal_error = InterruptedError("Codex turn was interrupted")
                        yield await self._publish(
                            self._emit(
                                RuntimeEventKind.TURN_INTERRUPTED,
                                turn_id=turn_id,
                                metadata=failure_metadata,
                            )
                        )
                        yield await self._publish(
                            self._emit(
                                RuntimeEventKind.INTERRUPTED,
                                turn_id=turn_id,
                                metadata=failure_metadata,
                            )
                        )
                    elif status == "completed":
                        self.result = self._result(turn)
                        yield await self._publish(
                            self._emit(
                                RuntimeEventKind.TURN_COMPLETED,
                                turn_id=turn_id,
                                metadata={"status": status},
                            )
                        )
                    else:
                        failure_metadata.update(_provider_error_metadata(turn))
                        self.terminal_error = RuntimeUnavailableError(
                            "Codex turn failed",
                            details=failure_metadata,
                        )
                        yield await self._publish(
                            self._emit(
                                RuntimeEventKind.TURN_FAILED,
                                turn_id=turn_id,
                                metadata=failure_metadata,
                            )
                        )
                    if self.terminal_error is None:
                        yield await self._publish(
                            self._emit(
                                RuntimeEventKind.INVOCATION_COMPLETED,
                                turn_id=turn_id,
                                metadata={"status": status},
                                result=self.result,
                            )
                        )
                    else:
                        yield await self._publish(
                            self._emit(
                                RuntimeEventKind.INVOCATION_FAILED,
                                turn_id=turn_id,
                                metadata=failure_metadata,
                            )
                        )
                        raise self.terminal_error
        except asyncio.CancelledError:
            with suppress(Exception):
                await self.interrupt()
            with suppress(Exception):
                await self._publish(
                    self._emit(
                        RuntimeEventKind.CANCELLED,
                        turn_id=turn_id,
                        metadata={"reason": "cancelled"},
                    )
                )
            raise
        except AgentRuntimeError:
            if self.terminal_status is None:
                yield await self._publish(
                    self._emit(
                        RuntimeEventKind.INVOCATION_FAILED,
                        turn_id=turn_id,
                        metadata={"reason": "transport"},
                    )
                )
            raise
        except Exception as exc:
            self.terminal_error = TransportError(
                "Codex turn stream failed",
                details={"exception_type": type(exc).__name__},
            )
            yield await self._publish(
                self._emit(
                    RuntimeEventKind.INVOCATION_FAILED,
                    turn_id=turn_id,
                    metadata={"reason": "transport"},
                )
            )
            raise self.terminal_error from exc
        finally:
            if self.cleanup is not None:
                self.cleanup()
                self.cleanup = None
            self.finished.set()
        if self.terminal_status is None:
            self.terminal_error = TransportError("Codex returned no terminal turn event")
            yield await self._publish(
                self._emit(
                    RuntimeEventKind.INVOCATION_FAILED,
                    turn_id=turn_id,
                    metadata={"reason": "missing_terminal"},
                )
            )
            raise self.terminal_error

    async def wait_finished(self) -> None:
        """Wait until the normalized event stream has finalized."""

        await self.finished.wait()

    def _result(self, turn: object | None) -> RuntimeResult[str]:
        """Build a normalized result from collected items and usage."""

        items = list(self.items)
        texts = [
            _item_text(item)
            for item in items
            if _item_type(item) in {"agentMessage", "agent_message"}
        ]
        output = "".join(texts) or "".join(self.deltas)
        duration = getattr(turn, "duration_ms", None) if turn is not None else None
        usage = usage_from_sdk(self.usage, duration_ms=duration)
        raw: object | None = None
        if self.include_raw:
            raw = safe_raw(
                {
                    "id": getattr(turn, "id", getattr(self.handle, "id", None)),
                    "status": enum_value(getattr(turn, "status", None)) if turn else "completed",
                    "type": "codex_turn",
                }
            )
        return RuntimeResult(
            output=output,
            usage=usage,
            runtime=self.identity,
            model=self.model,
            profile=self.profile,
            reasoning_effort=self.effort,
            session_id=self.session_id,
            turn_id=str(getattr(turn, "id", getattr(self.handle, "id", ""))) or None,
            raw=raw,
            task_id=self.task_id,
        )

    async def interrupt(self) -> None:
        """Request interruption of the active SDK turn."""

        await self.handle.interrupt()


def _item_text(item: object) -> str:
    """Extract text from legacy and current Codex agent-message item shapes."""

    item = getattr(item, "root", item)
    direct = getattr(item, "text", None)
    if direct:
        return str(direct)
    values: list[str] = []
    for content in getattr(item, "content", ()) or ():
        root = getattr(content, "root", content)
        text = getattr(root, "text", None)
        if text:
            values.append(str(text))
    return "".join(values)


def _item_type(item: object) -> str:
    """Return the type discriminator from a direct or root-wrapped item."""

    return str(getattr(getattr(item, "root", item), "type", ""))
