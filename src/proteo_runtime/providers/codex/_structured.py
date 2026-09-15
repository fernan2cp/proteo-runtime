"""Structured-output normalization and validation for the Codex provider."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ValidationError

from proteo_runtime.core.errors import (
    CancellationError,
    CapabilityError,
    RuntimeTimeoutError,
    StructuredOutputError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.model import (
    InvocationConfig,
    RuntimeResult,
    StructuredOutputPolicy,
)
from proteo_runtime.core.usage import RuntimeUsage

from ._runner import TurnRun
from .runtime import _enum, _map_sdk_error, _merge_invocation_config


class _ValidationFailure(Exception):
    """Internal normalized host validation failure."""

    def __init__(self, paths: tuple[str, ...]) -> None:
        """Store safe validation paths."""

        self.paths = paths
        super().__init__("structured output validation failed")


@dataclass(frozen=True)
class _SchemaAdapter:
    """Immutable schema and host validator for one structured model."""

    schema: dict[str, Any]
    model_type: type[BaseModel] | None
    validator: Draft202012Validator | None

    @classmethod
    def create(cls, schema: Any) -> _SchemaAdapter:
        """Normalize and validate a Pydantic class or JSON Schema mapping."""

        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return cls(_normalize_sdk_schema(schema.model_json_schema()), schema, None)
        if not isinstance(schema, dict):
            raise CapabilityError("Structured schema must be a Pydantic model or JSON object")
        copied = _normalize_sdk_schema(json.loads(json.dumps(schema)))
        try:
            Draft202012Validator.check_schema(copied)
            validator = Draft202012Validator(copied)
        except (SchemaError, TypeError, ValueError) as exc:
            raise CapabilityError("Invalid Draft 2020-12 structured schema") from exc
        return cls(copied, None, validator)

    def validate(self, output: str) -> Any:
        """Parse one JSON value and validate it on the host."""

        try:
            value = json.loads(output)
        except (TypeError, json.JSONDecodeError) as exc:
            raise _ValidationFailure(("$",)) from exc
        if self.model_type is not None:
            try:
                return self.model_type.model_validate(value)
            except ValidationError as exc:
                paths = tuple(_error_path(item.get("loc", ())) for item in exc.errors())
                raise _ValidationFailure(paths or ("$",)) from exc
        assert self.validator is not None
        errors = sorted(self.validator.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            paths = tuple(_error_path(error.path) for error in errors[:8])
            raise _ValidationFailure(paths or ("$",))
        return value


def _normalize_sdk_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Close object schemas for the Codex response-format contract."""

    def visit(value: Any) -> Any:
        """Recursively normalize object nodes and nested schema containers."""

        if isinstance(value, dict):
            normalized = {str(key): visit(item) for key, item in value.items()}
            if normalized.get("type") == "object" and "additionalProperties" not in normalized:
                normalized["additionalProperties"] = False
            return normalized
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    return cast(dict[str, Any], visit(schema))


def _error_path(parts: Any) -> str:
    """Convert a validator location to a bounded JSON path."""

    values = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(values) if values else "$"


def _redact_raw(value: str) -> str:
    """Apply conservative credential redaction to explicitly requested invalid output."""

    redacted = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", value)
    redacted = re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^,}\s]+", r"\1=[REDACTED]", redacted
    )
    try:
        parsed = json.loads(redacted)
    except (TypeError, json.JSONDecodeError):
        return redacted
    if isinstance(parsed, dict):
        return json.dumps(_redact_mapping(parsed), ensure_ascii=False, sort_keys=True)
    return redacted


def _redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Redact credential-shaped keys recursively in a JSON mapping."""

    result: dict[str, Any] = {}
    for key, item in value.items():
        if str(key).casefold().replace("-", "_") in {
            "api_key",
            "apikey",
            "token",
            "secret",
            "password",
            "authorization",
        }:
            result[str(key)] = "[REDACTED]"
        elif isinstance(item, Mapping):
            result[str(key)] = _redact_mapping(item)
        elif isinstance(item, list):
            result[str(key)] = [
                _redact_mapping(entry) if isinstance(entry, Mapping) else entry for entry in item
            ]
        else:
            result[str(key)] = item
    return result


def _sum_optional(values: list[int | float | None]) -> int | float | None:
    """Sum counters when every attempt reported a value."""

    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _aggregate_usage(usages: list[RuntimeUsage]) -> RuntimeUsage:
    """Aggregate usage across all structured validation attempts."""

    return RuntimeUsage(
        input_tokens=cast(int | None, _sum_optional([item.input_tokens for item in usages])),
        cached_input_tokens=cast(
            int | None, _sum_optional([item.cached_input_tokens for item in usages])
        ),
        output_tokens=cast(int | None, _sum_optional([item.output_tokens for item in usages])),
        reasoning_tokens=cast(
            int | None, _sum_optional([item.reasoning_tokens for item in usages])
        ),
        total_tokens=cast(int | None, _sum_optional([item.total_tokens for item in usages])),
        duration_ms=cast(float | None, _sum_optional([item.duration_ms for item in usages])),
        turn_count=sum(item.turn_count for item in usages),
        tool_call_count=sum(item.tool_call_count for item in usages),
        retry_count=sum(item.retry_count for item in usages) + max(0, len(usages) - 1),
        raw={"attempt_count": len(usages)},
    )


class StructuredCodexModel:
    """Codex model facade that returns host-validated structured values."""

    def __init__(self, base: Any, schema: Any, policy: StructuredOutputPolicy | None) -> None:
        """Bind an immutable normalized schema and retry policy."""

        self._base = base
        self._schema = _SchemaAdapter.create(schema)
        self._policy = policy or StructuredOutputPolicy()

    def with_structured_output(
        self, schema: Any, *, policy: StructuredOutputPolicy | None = None
    ) -> StructuredCodexModel:
        """Return a new structured facade with an independently validated schema."""

        return StructuredCodexModel(self._base, schema, policy or self._policy)

    async def effective_capabilities(self) -> Any:
        """Return capabilities effective for structured execution."""

        capabilities = await self._base.effective_capabilities()
        if not capabilities.structured_output:
            raise CapabilityError("Structured output is unavailable for this model")
        return capabilities

    async def ainvoke(
        self,
        input: str | Any,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> RuntimeResult[Any]:
        """Invoke and collect one validated structured result."""

        terminal: RuntimeResult[Any] | None = None
        async for event in self.astream(input, config=config, include_raw=include_raw):
            if event.kind is RuntimeEventKind.INVOCATION_COMPLETED:
                terminal = event.result
        if terminal is None:
            raise StructuredOutputError("Structured invocation returned no validated result")
        return terminal

    async def astream(
        self,
        input: str | Any,
        *,
        config: InvocationConfig | None = None,
        include_raw: bool | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Stream lifecycle and validation events while buffering structured text."""

        active: list[TurnRun | None] = [None]
        effective = _merge_invocation_config(self._base.config, config)
        raw_requested = bool(effective.include_raw if include_raw is None else include_raw)
        try:
            timeout = effective.timeout_seconds
            if timeout is None:
                async for event in self._events(input, effective, raw_requested, active):
                    yield event
            else:
                async with asyncio.timeout(timeout):
                    async for event in self._events(input, effective, raw_requested, active):
                        yield event
        except TimeoutError as exc:
            if active[0] is not None:
                await self._base._interrupt_or_invalidate(active[0])
            raise RuntimeTimeoutError("Structured Codex invocation timed out") from exc
        except asyncio.CancelledError as exc:
            if active[0] is not None:
                await self._base._interrupt_or_invalidate(active[0])
            raise CancellationError("Structured Codex invocation was cancelled") from exc

    async def _events(
        self,
        input: str | Any,
        config: InvocationConfig,
        raw_requested: bool,
        active: list[TurnRun | None],
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute attempts and yield the logical buffered event stream."""

        await self.effective_capabilities()
        logical_id = uuid4().hex
        run, workspace = await self._base._start_run(
            input,
            raw_requested,
            config,
            output_schema=self._schema.schema,
        )
        thread = getattr(run, "provider_thread", None)
        usages: list[RuntimeUsage] = []
        last_output = ""
        last_paths: tuple[str, ...] = ("$",)
        sequence = 0
        try:
            yield self._event(
                RuntimeEventKind.INVOCATION_STARTED,
                logical_id,
                sequence,
                {"max_attempts": self._policy.max_attempts},
            )
            sequence += 1
            for attempt in range(1, self._policy.max_attempts + 1):
                active[0] = run
                provider_events: list[RuntimeEvent] = []
                try:
                    async for event in run.events():
                        provider_events.append(event)
                finally:
                    if run.terminal_status is None:
                        await self._base._interrupt_or_invalidate(run)
                    self._base.runtime._unregister_run(run)
                    active[0] = None
                if run.result is None:
                    raise StructuredOutputError(
                        "Codex returned no structured result", attempts=attempt
                    )
                usages.append(run.result.usage)
                last_output = run.result.output
                for event in provider_events:
                    if event.kind in {
                        RuntimeEventKind.OUTPUT_TEXT_DELTA,
                        RuntimeEventKind.INVOCATION_COMPLETED,
                        RuntimeEventKind.INVOCATION_STARTED,
                    }:
                        continue
                    yield replace(
                        event,
                        event_id=f"{logical_id}:{sequence}",
                        invocation_id=logical_id,
                        sequence=sequence,
                        metadata={**event.metadata, "attempt": attempt},
                    )
                    sequence += 1
                try:
                    value = self._schema.validate(last_output)
                except _ValidationFailure as failure:
                    last_paths = failure.paths
                    yield self._event(
                        RuntimeEventKind.VALIDATION_FAILED,
                        logical_id,
                        sequence,
                        {"attempt": attempt, "paths": last_paths},
                        turn_id=run.result.turn_id,
                    )
                    sequence += 1
                    if attempt >= self._policy.max_attempts:
                        raise StructuredOutputError(
                            "Structured output validation attempts exhausted",
                            attempts=attempt,
                            validation_paths=last_paths,
                            raw=_redact_raw(last_output) if raw_requested else None,
                        ) from failure
                    yield self._event(
                        RuntimeEventKind.RETRY_SCHEDULED,
                        logical_id,
                        sequence,
                        {"attempt": attempt, "next_attempt": attempt + 1},
                        turn_id=run.result.turn_id,
                    )
                    sequence += 1
                    if thread is None:
                        raise StructuredOutputError(
                            "Structured retry requires a reusable Codex thread",
                            attempts=attempt,
                            validation_paths=last_paths,
                        ) from failure
                    feedback = _feedback(last_paths)
                    try:
                        handle = await thread.turn(
                            feedback,
                            model=run.model,
                            effort=run.effort,
                            output_schema=self._schema.schema,
                            approval_mode=_enum("ApprovalMode", "deny_all"),
                            sandbox=_enum("Sandbox", "read_only"),
                        )
                    except Exception as exc:
                        raise _map_sdk_error(exc, "structured retry") from exc
                    run = TurnRun(
                        runtime_name="codex",
                        identity=self._base.runtime.identity,
                        handle=handle,
                        invocation_id=uuid4().hex,
                        model=run.model,
                        profile=run.profile,
                        effort=run.effort,
                        include_raw=raw_requested,
                    )
                    run.provider_thread = thread
                    self._base.runtime._register_run(run)
                    continue
                result = RuntimeResult(
                    value=value,
                    usage=_aggregate_usage(usages),
                    runtime=run.result.runtime,
                    model=run.result.model,
                    profile=run.result.profile,
                    reasoning_effort=run.result.reasoning_effort,
                    session_id=run.result.session_id,
                    turn_id=run.result.turn_id,
                    diagnostics=run.result.diagnostics,
                    raw=run.result.raw if raw_requested else None,
                )
                yield self._event(
                    RuntimeEventKind.INVOCATION_COMPLETED,
                    logical_id,
                    sequence,
                    {"attempt": attempt},
                    result,
                )
                sequence += 1
                return
        finally:
            self._base.runtime._unregister_run(run)
            from ._workspace import remove_workspace

            remove_workspace(workspace)

    def _event(
        self,
        kind: RuntimeEventKind,
        invocation_id: str,
        sequence: int,
        metadata: Mapping[str, Any],
        result: RuntimeResult[Any] | None = None,
        turn_id: str | None = None,
    ) -> RuntimeEvent:
        """Build a logical structured event."""

        return RuntimeEvent(
            kind=kind,
            event_id=f"{invocation_id}:{sequence}",
            sequence=sequence,
            occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            runtime=self._base.runtime.identity,
            invocation_id=invocation_id,
            turn_id=turn_id,
            metadata=metadata,
            result=result,
        )


def _feedback(paths: tuple[str, ...]) -> str:
    """Build bounded validation feedback without embedding invalid output."""

    bounded = ", ".join(paths[:8])[:500]
    return f"Return one JSON value that satisfies the schema. Correct these paths: {bounded}."
