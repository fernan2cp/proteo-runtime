"""Optional LangSmith observer built on the neutral Proteo event contract."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import Any
from uuid import UUID

from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind


class LangSmithObserver:
    """Export Proteo events as nested LangSmith runs when installed."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        project_name: str | None = None,
        tags: tuple[str, ...] = (),
        owns_client: bool | None = None,
    ) -> None:
        """Initialize with an optional injected client for deterministic tests."""

        supplied_client = client is not None
        if client is None:
            try:
                from langsmith import Client
            except ImportError as exc:
                raise ImportError(
                    "LangSmithObserver requires optional dependency; install proteo-runtime[langsmith]"
                ) from exc
            client = Client()
        self.client = client
        self._owns_client = not supplied_client if owns_client is None else owns_client
        self.project_name = project_name
        self.tags = tags
        self._runs: dict[tuple[str, str], Any] = {}
        self._pending: set[asyncio.Task[Any]] = set()
        self._closed = False

    async def on_event(self, event: RuntimeEvent) -> None:
        """Create or update one LangSmith run without blocking the event loop."""

        if self._closed:
            return
        await asyncio.to_thread(self._handle_event, event)

    def _handle_event(self, event: RuntimeEvent) -> None:
        """Synchronously map one event for execution in a worker thread."""

        invocation = event.invocation_id or event.event_id
        if event.kind is RuntimeEventKind.INVOCATION_STARTED:
            self._create_run((invocation, "runtime"), "proteo.runtime", event, None)
            return
        root = self._runs.get((invocation, "runtime"))
        if event.kind is RuntimeEventKind.TURN_STARTED:
            self._create_run((invocation, "turn"), "proteo.turn", event, root)
        elif event.kind in {
            RuntimeEventKind.RETRY_SCHEDULED,
            RuntimeEventKind.TOOL_RETRY_SCHEDULED,
        }:
            key = (invocation, f"retry:{event.metadata.get('attempt', '')}")
            self._create_run(
                key,
                "proteo.retry",
                event,
                self._runs.get((invocation, "turn")) or root,
            )
            self._finish_keys((key,), event)
        elif event.kind is RuntimeEventKind.VALIDATION_FAILED:
            key = (invocation, f"validation:{event.metadata.get('attempt', '')}")
            self._create_run(
                key,
                "proteo.validation",
                event,
                self._runs.get((invocation, "turn")) or root,
            )
            self._finish_keys((key,), event)
        elif event.kind in {
            RuntimeEventKind.TOOL_REQUESTED,
            RuntimeEventKind.TOOL_STARTED,
            RuntimeEventKind.TOOL_APPROVAL_REQUESTED,
        }:
            self._create_run(
                (invocation, self._tool_key(event)),
                "proteo.tool",
                event,
                self._runs.get((invocation, "turn")) or root,
            )
        elif event.kind in {
            RuntimeEventKind.TOOL_COMPLETED,
            RuntimeEventKind.TOOL_DENIED,
            RuntimeEventKind.TOOL_FAILED,
        }:
            key = (invocation, self._tool_key(event))
            if key not in self._runs:
                open_tools = [
                    item
                    for item in self._runs
                    if item[0] == invocation and item[1].startswith("tool:")
                ]
                key = open_tools[-1] if open_tools else key
            if key in self._runs:
                self._finish_keys((key,), event)

        if event.kind in {
            RuntimeEventKind.TURN_COMPLETED,
            RuntimeEventKind.TURN_FAILED,
            RuntimeEventKind.TURN_INTERRUPTED,
            RuntimeEventKind.INVOCATION_COMPLETED,
            RuntimeEventKind.INVOCATION_FAILED,
            RuntimeEventKind.CANCELLED,
            RuntimeEventKind.INTERRUPTED,
        }:
            self._finish_matching(invocation, event)

    def _create_run(
        self, key: tuple[str, str], name: str, event: RuntimeEvent, parent: Any | None
    ) -> None:
        """Create one run using the SDK's stable client method."""

        if key in self._runs:
            return
        metadata = dict(event.metadata)
        parent_candidate = metadata.get("langgraph_run_id") or metadata.get("parent_run_id")
        parent_id = _valid_parent_id(parent_candidate)
        if parent is not None:
            parent_id = _run_id(parent)
        kwargs: dict[str, Any] = {
            "name": name,
            "run_type": "chain",
            "inputs": _safe_inputs(event),
            "start_time": int(event.occurred_at.timestamp() * 1000),
            "extra": {"metadata": _materialize(metadata)},
            "tags": list(self.tags),
        }
        if self.project_name:
            kwargs["project_name"] = self.project_name
        if parent_id:
            kwargs["parent_run_id"] = parent_id
        run = _call_client(self.client, "create_run", kwargs)
        self._runs[key] = run if run is not None else kwargs.get("id", key[1])

    def _finish_matching(self, invocation: str, event: RuntimeEvent) -> None:
        """Mark all relevant nested runs complete for a terminal event."""

        keys = [key for key in self._runs if key[0] == invocation]
        if event.kind in {
            RuntimeEventKind.TURN_COMPLETED,
            RuntimeEventKind.TURN_FAILED,
            RuntimeEventKind.TURN_INTERRUPTED,
        }:
            keys = [key for key in keys if key[1] != "runtime"]
        self._finish_keys(keys, event)

    def _finish_keys(
        self, keys: tuple[tuple[str, str], ...] | list[tuple[str, str]], event: RuntimeEvent
    ) -> None:
        """Finish a selected set of runs exactly once."""

        for key in keys:
            if key not in self._runs:
                continue
            run = self._runs.pop(key)
            kwargs = {
                "run_id": _run_id(run),
                "outputs": _safe_outputs(event),
                "end_time": int(event.occurred_at.timestamp() * 1000),
                "error": event.metadata.get("status")
                if event.kind in {RuntimeEventKind.INVOCATION_FAILED, RuntimeEventKind.TURN_FAILED}
                else None,
            }
            _call_client(self.client, "update_run", kwargs)

    @staticmethod
    def _tool_key(event: RuntimeEvent) -> str:
        """Build a stable tool run key from neutral tool metadata."""

        metadata = event.metadata
        tool_id = metadata.get("tool_call_id") or metadata.get("tool_name") or metadata.get("name")
        return f"tool:{tool_id or 'default'}"

    async def flush(self) -> None:
        """Flush any client-owned batches when supported."""

        if self._closed:
            return
        flush = getattr(self.client, "flush", None)
        if flush is not None:
            await asyncio.to_thread(flush)

    async def close(self) -> None:
        """Close the client only when this observer owns its lifecycle."""

        if self._closed:
            return
        self._closed = True
        if not self._owns_client:
            return
        close = getattr(self.client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)


def _call_client(client: Any, method: str, kwargs: dict[str, Any]) -> Any:
    """Call a LangSmith client method while tolerating older test doubles."""

    callback = getattr(client, method, None)
    if callback is None:
        return None
    try:
        return callback(**kwargs)
    except TypeError:
        reduced = {
            key: value
            for key, value in kwargs.items()
            if key not in {"start_time", "end_time", "error"}
        }
        return callback(**reduced)


def _run_id(run: Any) -> str | None:
    """Extract an SDK run identifier from objects and mappings."""

    if isinstance(run, Mapping):
        value = run.get("id") or run.get("run_id")
    else:
        value = getattr(run, "id", getattr(run, "run_id", run))
    return str(value) if value else None


def _valid_parent_id(value: Any) -> str | None:
    """Accept only UUID-shaped parent IDs supplied by a LangGraph host."""

    if not isinstance(value, str):
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


def _safe_inputs(event: RuntimeEvent) -> dict[str, Any]:
    """Return observer-projected run inputs without arbitrary provider objects."""

    inputs: dict[str, Any] = {"event_id": event.event_id, "kind": event.kind.value}
    if event.payload:
        inputs["payload"] = _materialize(event.payload)
    return inputs


def _safe_outputs(event: RuntimeEvent) -> dict[str, Any]:
    """Return observer-projected terminal outputs and usage metadata."""

    result = event.result
    outputs: dict[str, Any] = {
        "kind": event.kind.value,
        "status": event.metadata.get("status"),
        "turn_id": event.turn_id,
        "usage": (
            {field.name: getattr(result.usage, field.name) for field in fields(result.usage)}
            if result is not None and is_dataclass(result.usage)
            else None
        ),
    }
    if result is not None:
        outputs["value"] = _materialize(result.value)
    if event.payload:
        outputs["payload"] = _materialize(event.payload)
    return outputs


def _materialize(value: Any) -> Any:
    """Convert projected immutable containers to SDK-serializable values."""

    if isinstance(value, Mapping):
        return {str(key): _materialize(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_materialize(item) for item in value]
    if value is None or isinstance(value, str | bool | int | float):
        return value
    return f"<{type(value).__name__}>"


__all__ = ["LangSmithObserver"]
