"""Provider-neutral async node implementation for LangGraph."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, Generic, Literal, TypeVar, cast

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from proteo_runtime.core.errors import (
    CancellationError,
    ConfigurationError,
    RuntimeUnavailableError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity
from proteo_runtime.core.input import RuntimeInput
from proteo_runtime.core.model import InvocationConfig, RuntimeModel, RuntimeResult
from proteo_runtime.core.runtime import Runtime
from proteo_runtime.core.session import RuntimeSession
from proteo_runtime.core.types import is_secret_key

StateT = TypeVar("StateT")
InputMapper = Callable[[StateT], str | RuntimeInput]
OutputMapper = Callable[[RuntimeResult[Any]], Mapping[str, Any]]
ExecutorMode = Literal["model", "runtime"]

_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._-]+|"
    r"((?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*)[^,}\s]+"
)


def _looks_like_model(value: object) -> bool:
    """Recognize legacy test doubles that predate the optional tool binding method."""

    return all(
        hasattr(value, attribute)
        for attribute in ("ainvoke", "astream", "with_structured_output", "effective_capabilities")
    )


class RuntimeNode(Generic[StateT]):
    """Expose a Proteo runtime model or resumable session as an async graph node."""

    def __init__(
        self,
        executor: RuntimeModel[Any] | Runtime,
        *,
        input_key: str = "input",
        output_key: str = "output",
        input_mapper: InputMapper[StateT] | None = None,
        output_mapper: OutputMapper | None = None,
    ) -> None:
        """Validate and retain an immutable node mapping configuration."""

        if not input_key or not output_key:
            raise ValueError("input_key and output_key must be non-empty")
        model_match = isinstance(executor, RuntimeModel) or _looks_like_model(executor)
        runtime_match = isinstance(executor, Runtime)
        if model_match == runtime_match:
            raise TypeError("executor must implement exactly one of RuntimeModel or Runtime")
        self._executor = executor
        self._mode: ExecutorMode = "model" if model_match else "runtime"
        self._input_key = input_key
        self._output_key = output_key
        self._input_mapper = input_mapper
        self._output_mapper = output_mapper

    async def __call__(
        self,
        state: StateT,
        config: RunnableConfig = None,  # type: ignore[assignment]
    ) -> Mapping[str, Any]:
        """Execute one graph node turn and return a state update mapping."""

        runtime_config = _invocation_config(config)
        runtime_input = self._to_input(state)
        session: RuntimeSession[Any] | None = None
        stream: AsyncIterator[RuntimeEvent] | None = None
        failure: BaseException | None = None
        cleanup_error: BaseException | None = None
        cancel_requested = False
        try:
            if self._mode == "model":
                configurable = _configurable(config)
                if "proteo_session_id" in configurable:
                    raise ConfigurationError(
                        "Session descriptors are not accepted by a model node",
                        path="config.configurable.proteo_session_id",
                    )
                executor = cast(RuntimeModel[Any], self._executor)
                stream = executor.astream(runtime_input, config=runtime_config)
            else:
                session_id = _session_id(config)
                runtime_executor = cast(Runtime, self._executor)
                session = await runtime_executor.resume_session(session_id)
                stream = session.astream(runtime_input, config=runtime_config)
            assert stream is not None
            result = await self._consume_stream(stream)
            return self._to_output(result)
        except asyncio.CancelledError as exc:
            cancel_requested = True
            failure = exc
            raise
        except CancellationError as exc:
            if _task_is_cancelling():
                cancel_requested = True
                failure = exc
                raise asyncio.CancelledError() from exc
            failure = exc
            raise
        except BaseException as exc:
            failure = exc
            raise
        finally:
            if stream is not None:
                try:
                    await _close_stream(stream)
                except BaseException as exc:
                    if failure is None and not cancel_requested:
                        cleanup_error = exc
            if session is not None:
                try:
                    await session.close()
                except BaseException as exc:
                    if failure is None and not cancel_requested and cleanup_error is None:
                        cleanup_error = exc
            if failure is None and cleanup_error is not None:
                raise cleanup_error

    async def _consume_stream(self, stream: AsyncIterator[RuntimeEvent]) -> RuntimeResult[Any]:
        """Drain a neutral event stream and return its unique successful result."""

        writer = get_stream_writer()
        result: RuntimeResult[Any] | None = None
        for_terminal = False
        async for event in stream:
            writer(_project_event(event))
            if event.kind is not RuntimeEventKind.INVOCATION_COMPLETED:
                continue
            if for_terminal:
                raise RuntimeUnavailableError(
                    "Runtime stream emitted multiple successful terminals"
                )
            for_terminal = True
            if event.result is None:
                raise RuntimeUnavailableError("Runtime stream completed without a result")
            result = event.result
        if result is None:
            raise RuntimeUnavailableError("Runtime stream ended without a successful result")
        return result

    def _to_input(self, state: StateT) -> RuntimeInput:
        """Convert graph state through the configured input boundary."""

        value: object
        if self._input_mapper is not None:
            value = self._input_mapper(state)
        else:
            if not isinstance(state, Mapping):
                raise TypeError("Default RuntimeNode input mapping requires a Mapping state")
            if self._input_key not in state:
                raise ConfigurationError(
                    "RuntimeNode input key is missing", path=f"state.{self._input_key}"
                )
            value = state[self._input_key]
        return RuntimeInput.from_value(cast(str | RuntimeInput, value))

    def _to_output(self, result: RuntimeResult[Any]) -> Mapping[str, Any]:
        """Convert a neutral result into a copied graph state update."""

        if self._output_mapper is None:
            return {self._output_key: result.value}
        mapped = self._output_mapper(result)
        if not isinstance(mapped, Mapping):
            raise TypeError("RuntimeNode output_mapper must return a Mapping")
        return dict(mapped)


def _configurable(config: RunnableConfig | None) -> Mapping[str, Any]:
    """Return the read-only configurable namespace or an empty mapping."""

    if config is None:
        return {}
    value = config.get("configurable")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigurationError(
            "RunnableConfig.configurable must be a mapping", path="config.configurable"
        )
    return value


def _session_id(config: RunnableConfig | None) -> str:
    """Validate and return the host-owned persistent session descriptor."""

    configurable = _configurable(config)
    value = configurable.get("proteo_session_id")
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            "A persistent RuntimeNode requires a non-empty session descriptor",
            path="config.configurable.proteo_session_id",
        )
    return value


def _invocation_config(config: RunnableConfig | None) -> InvocationConfig:
    """Build a fresh invocation config from the safe RunnableConfig subset."""

    if config is None:
        return InvocationConfig()
    source = config.get("metadata")
    if source is not None and not isinstance(source, Mapping):
        raise ConfigurationError(
            "RunnableConfig.metadata must be a mapping", path="config.metadata"
        )
    metadata: dict[str, Any] = {}
    if isinstance(source, Mapping):
        proteo = source.get("proteo")
        if proteo is not None:
            if not isinstance(proteo, Mapping):
                raise ConfigurationError(
                    "config.metadata.proteo must be a mapping", path="config.metadata.proteo"
                )
            metadata["proteo"] = _copy_json(proteo, "config.metadata.proteo")
        framework: dict[str, Any] = {}
        for key in ("langgraph_node", "langgraph_step", "langgraph_triggers"):
            if key in source:
                framework[key] = _copy_json(source[key], f"config.metadata.{key}")
        if framework:
            metadata["langgraph"] = framework
    tags = config.get("tags")
    tags_value: object = cast(object, tags)
    if tags_value is not None:
        if (
            not isinstance(tags_value, Sequence)
            or isinstance(tags_value, str)
            or not all(isinstance(tag, str) for tag in tags_value)
        ):
            raise ConfigurationError(
                "RunnableConfig.tags must be a sequence of strings", path="config.tags"
            )
        metadata["langgraph_tags"] = list(tags_value)
    run_id = config.get("run_id")
    if run_id is not None:
        metadata["langgraph_run_id"] = str(run_id)
    return InvocationConfig(metadata=metadata)


def _copy_json(value: object, path: str) -> object:
    """Copy a JSON-compatible value while rejecting unsafe metadata."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigurationError("Metadata floats must be finite", path=path)
        return value
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            normalized = str(key)
            if is_secret_key(normalized):
                raise ConfigurationError(
                    "Secret-shaped metadata keys are not permitted", path=f"{path}.{normalized}"
                )
            copied[normalized] = _copy_json(item, f"{path}.{normalized}")
        return copied
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_copy_json(item, f"{path}[]") for item in value]
    raise ConfigurationError(
        f"Metadata value type {type(value).__name__} is not JSON-compatible", path=path
    )


def _project_event(event: RuntimeEvent) -> dict[str, Any]:
    """Project a neutral runtime event into a JSON-safe LangGraph envelope."""

    runtime = event.runtime
    if isinstance(runtime, RuntimeIdentity):
        runtime_value: dict[str, Any] = {
            "provider": runtime.provider,
            "fingerprint": runtime.fingerprint,
        }
    else:
        runtime_value = {"provider": str(runtime)}
    return {
        "type": "proteo_runtime_event",
        "version": 1,
        "event": {
            "kind": event.kind.value,
            "event_id": event.event_id,
            "sequence": event.sequence,
            "occurred_at": event.occurred_at.isoformat(),
            "runtime": runtime_value,
            "invocation_id": event.invocation_id,
            "session_correlation_id": _session_correlation_id(event.session_id),
            "turn_id": event.turn_id,
            "metadata": _project_json(event.metadata),
        },
    }


def _project_json(value: object) -> object:
    """Convert event metadata to JSON-safe values and omit secret-shaped fields."""

    if value is None or isinstance(value, str | bool | int):
        return _redact_text(value) if isinstance(value, str) else value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {
            str(key): _project_json(item)
            for key, item in value.items()
            if not is_secret_key(str(key))
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_project_json(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_project_json(item) for item in sorted(value, key=repr)]
    return None


def _redact_text(value: str) -> str:
    """Redact common credential-shaped assignments from event text."""

    return _SECRET_VALUE_PATTERN.sub(
        lambda match: f"{match.group(1) or match.group(2) or ''}[REDACTED]", value
    )


def _session_correlation_id(session_id: str | None) -> str | None:
    """Return a non-reversible correlation digest for a session descriptor."""

    if session_id is None:
        return None
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _task_is_cancelling() -> bool:
    """Return whether the current asyncio task has a pending cancellation request."""

    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _close_stream(stream: AsyncIterator[RuntimeEvent]) -> None:
    """Close an async stream when it exposes the standard async-generator hook."""

    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()
