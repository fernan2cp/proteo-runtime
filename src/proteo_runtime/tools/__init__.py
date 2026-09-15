"""Provider-neutral contracts for host-managed tools.

The module deliberately contains no provider or framework imports.  A registry keeps
the executable bindings private while exposing immutable, JSON-safe definitions to a
provider adapter.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, cast, get_type_hints

from jsonschema import Draft202012Validator, SchemaError
from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model
from pydantic.errors import PydanticSchemaGenerationError, PydanticUndefinedAnnotation

from proteo_runtime.core.errors import (
    RetryExhaustedError,
    ToolDeniedError,
    ToolExecutionError,
)
from proteo_runtime.core.events import RuntimeEvent, RuntimeEventKind
from proteo_runtime.core.identity import RuntimeIdentity

__all__ = [
    "ApprovalDecision",
    "ApprovalHandler",
    "ApprovalRequest",
    "ApprovalRequirement",
    "SideEffect",
    "ToolDefinition",
    "ToolExecutor",
    "ToolFailurePolicy",
    "ToolPermissionPolicy",
    "ToolRegistry",
    "ToolRequest",
    "ToolResult",
    "ToolRetryPolicy",
    "ToolSnapshot",
    "runtime_tool",
]

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_T = TypeVar("_T")


class SideEffect(StrEnum):
    """Classify the side effects a tool may cause."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ApprovalRequirement(StrEnum):
    """Specify when a tool requires host approval."""

    NEVER = "never"
    ALWAYS = "always"
    FOR_SIDE_EFFECTS = "for_side_effects"


class ApprovalDecision(StrEnum):
    """Allowed responses from an approval handler."""

    APPROVE = "approve"
    DENY = "deny"


class ToolFailurePolicy(StrEnum):
    """Select whether tool errors are returned to the model or raised."""

    RETURN_ERROR = "return_error"
    RAISE = "raise"


class ApprovalHandler(Protocol):
    """Asynchronous host callback used for human or policy approval."""

    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        """Return an approval decision for one validated request."""


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-compatible values without retaining arbitrary objects."""

    if value is None or isinstance(value, str | int | float | bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise TypeError("non-finite numbers are not JSON-safe")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        frozen = tuple(_freeze(item) for item in value)
        return tuple(sorted(frozen, key=lambda item: json.dumps(_thaw(item), sort_keys=True)))
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


def _thaw(value: Any) -> Any:
    """Materialize frozen JSON values for a callable or provider serializer."""

    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe value or raise a validation error."""

    frozen = _freeze(value)
    materialized = _thaw(frozen)
    json.dumps(materialized, ensure_ascii=False, allow_nan=False)
    return frozen


def _schema_for(annotation: Any) -> dict[str, Any]:
    """Generate and validate a Draft 2020-12 schema from one annotation."""

    if annotation is inspect.Signature.empty or annotation is Any:
        raise TypeError("tool annotations must be concrete")
    try:
        schema = TypeAdapter(annotation).json_schema()
        Draft202012Validator.check_schema(schema)
    except (
        PydanticSchemaGenerationError,
        PydanticUndefinedAnnotation,
        SchemaError,
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError("annotation cannot produce a valid Draft 2020-12 schema") from exc
    return schema


class _InputModel(BaseModel):
    """Base configuration for generated tool argument models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _build_input_model(function: Callable[..., Any], name: str) -> type[BaseModel]:
    """Build a strict Pydantic model for a typed callable signature."""

    try:
        hints = get_type_hints(function)
    except (NameError, TypeError, PydanticUndefinedAnnotation) as exc:
        raise TypeError("tool annotations could not be resolved") from exc
    fields: dict[str, Any] = {}
    for parameter in inspect.signature(function).parameters.values():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            raise TypeError("variadic tool signatures are not supported")
        if parameter.kind is parameter.POSITIONAL_ONLY:
            raise TypeError("positional-only tool parameters are not supported")
        annotation = hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Signature.empty or annotation is Any:
            raise TypeError(f"missing annotation for parameter {parameter.name!r}")
        default = parameter.default if parameter.default is not inspect.Signature.empty else ...
        fields[parameter.name] = (annotation, default)
    try:
        model = create_model(
            f"{name.title().replace('-', '_')}Input", __base__=_InputModel, **fields
        )
        return cast(type[BaseModel], model)
    except (
        PydanticSchemaGenerationError,
        PydanticUndefinedAnnotation,
        TypeError,
        ValueError,
    ) as exc:
        raise TypeError("tool signature cannot be represented as a schema") from exc


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Immutable public description of one host-managed tool."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    permission: str
    side_effect: SideEffect = SideEffect.NONE
    idempotent: bool = False
    approval: ApprovalRequirement = ApprovalRequirement.FOR_SIDE_EFFECTS
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        """Validate metadata and deeply freeze the published schemas."""

        if not _NAME_RE.fullmatch(self.name):
            raise ValueError("tool name must match the portable tool-name grammar")
        if not self.description.strip() or not self.permission.strip():
            raise ValueError("tool description and permission are required")
        if self.timeout_seconds is not None and (
            not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        try:
            input_schema = _freeze(self.input_schema)
            output_schema = _freeze(self.output_schema)
            Draft202012Validator.check_schema(_thaw(input_schema))
            Draft202012Validator.check_schema(_thaw(output_schema))
        except (TypeError, ValueError, SchemaError) as exc:
            raise ValueError("tool schemas must be valid Draft 2020-12 objects") from exc
        object.__setattr__(self, "input_schema", input_schema)
        object.__setattr__(self, "output_schema", output_schema)
        object.__setattr__(self, "side_effect", SideEffect(self.side_effect))
        object.__setattr__(self, "approval", ApprovalRequirement(self.approval))

    def as_provider_dict(self) -> dict[str, Any]:
        """Return a JSON-safe provider description without the callable binding."""

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": _thaw(self.input_schema),
            "outputSchema": _thaw(self.output_schema),
        }


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Immutable request received from a provider adapter."""

    invocation_id: str
    call_id: str
    name: str
    arguments: Mapping[str, Any]
    session_id: str | None = None
    turn_id: str | None = None

    def __post_init__(self) -> None:
        """Validate identifiers and freeze JSON-safe arguments."""

        if not self.invocation_id or not self.call_id or not self.name:
            raise ValueError("invocation_id, call_id and name are required")
        object.__setattr__(self, "arguments", _json_safe(self.arguments))


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Validated request presented to an approval handler."""

    invocation_id: str
    call_id: str
    tool_name: str
    permission: str
    side_effect: SideEffect
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Freeze validated arguments and normalize the side-effect enum."""

        object.__setattr__(self, "side_effect", SideEffect(self.side_effect))
        object.__setattr__(self, "arguments", _json_safe(self.arguments))


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Sanitized neutral result returned to a provider adapter."""

    invocation_id: str
    call_id: str
    tool_name: str
    success: bool
    output: Any = None
    error_code: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0
    denied: bool = False
    timed_out: bool = False

    def __post_init__(self) -> None:
        """Ensure result output is immutable and JSON-safe."""

        if self.output is not None:
            object.__setattr__(self, "output", _json_safe(self.output))
        if self.attempts < 0 or self.duration_ms < 0:
            raise ValueError("attempts and duration_ms must be non-negative")

    def as_provider_value(self) -> Any:
        """Return a JSON-safe materialized output for a provider response."""

        return _thaw(self.output)


@dataclass(frozen=True, slots=True)
class ToolRetryPolicy:
    """Bounded retry policy; transport backoff belongs to a later phase."""

    max_attempts: int = 1

    def __post_init__(self) -> None:
        """Restrict attempts to the Phase 5 safety limit."""

        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")


@dataclass(frozen=True, slots=True)
class ToolPermissionPolicy:
    """Exact-match permission allow-list."""

    allowed_permissions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """Normalize and reject empty permission entries."""

        permissions = frozenset(str(item) for item in self.allowed_permissions)
        if any(not item.strip() for item in permissions):
            raise ValueError("permissions must be non-empty")
        object.__setattr__(self, "allowed_permissions", permissions)

    def allows(self, permission: str) -> bool:
        """Return whether the exact permission is present."""

        return permission in self.allowed_permissions


@dataclass(frozen=True, slots=True)
class _Binding:
    """Private executable binding paired with a public definition."""

    definition: ToolDefinition
    function: Callable[..., Awaitable[Any]]
    input_model: type[BaseModel]
    output_adapter: TypeAdapter[Any]


class _OutputValidationError(ToolExecutionError):
    """Mark output validation failures as terminal, non-retryable errors."""


@dataclass(frozen=True, slots=True)
class ToolSnapshot:
    """Read-only registry snapshot captured by a model or executor."""

    _bindings: Mapping[str, _Binding]

    def __post_init__(self) -> None:
        """Freeze the binding map and preserve insertion order."""

        object.__setattr__(self, "_bindings", MappingProxyType(dict(self._bindings)))

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return immutable definitions in registration order."""

        return tuple(binding.definition for binding in self._bindings.values())

    def get(self, name: str) -> ToolDefinition | None:
        """Return a definition without exposing its callable."""

        binding = self._bindings.get(name)
        return binding.definition if binding else None

    def provider_definitions(self) -> tuple[dict[str, Any], ...]:
        """Return serialized schemas safe for an experimental provider."""

        return tuple(definition.as_provider_dict() for definition in self.definitions())


class ToolRegistry:
    """Ordered registry that keeps executable callables private."""

    def __init__(self) -> None:
        """Initialize an empty registry."""

        self._bindings: dict[str, _Binding] = {}

    def register(
        self,
        tool: ToolDefinition | Callable[..., Any],
        callable_: Callable[..., Awaitable[Any]] | None = None,
    ) -> ToolDefinition:
        """Register a decorated function or an explicit definition and callable."""

        if callable(tool):
            definition = getattr(tool, "__runtime_tool_definition__", None)
            function = cast(Callable[..., Awaitable[Any]], tool)
            input_model = getattr(tool, "__runtime_tool_input_model__", None)
            output_adapter = getattr(tool, "__runtime_tool_output_adapter__", None)
            if not isinstance(definition, ToolDefinition) or input_model is None:
                raise TypeError("callable must be decorated with runtime_tool")
            if not isinstance(output_adapter, TypeAdapter):
                raise TypeError("decorated callable is missing a return adapter")
            binding = _Binding(definition, function, input_model, output_adapter)
        else:
            definition = tool
            if callable_ is None or not inspect.iscoroutinefunction(callable_):
                raise TypeError("an async callable is required for a ToolDefinition")
            input_model = _build_input_model(callable_, definition.name)
            try:
                return_annotation = get_type_hints(callable_).get("return", inspect.Signature.empty)
            except (NameError, TypeError, PydanticUndefinedAnnotation) as exc:
                raise TypeError("tool return annotation could not be resolved") from exc
            if return_annotation is inspect.Signature.empty or return_annotation is Any:
                raise TypeError("tool return annotation is required")
            try:
                output_adapter = TypeAdapter(return_annotation)
            except (PydanticSchemaGenerationError, TypeError, ValueError) as exc:
                raise TypeError("tool return annotation cannot be represented") from exc
            binding = _Binding(definition, callable_, input_model, output_adapter)
        if definition.name in self._bindings:
            raise ValueError(f"duplicate tool name: {definition.name}")
        self._bindings[definition.name] = binding
        return definition

    def get(self, name: str) -> ToolDefinition | None:
        """Return a registered definition without exposing executable state."""

        binding = self._bindings.get(name)
        return binding.definition if binding else None

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return definitions in deterministic insertion order."""

        return tuple(binding.definition for binding in self._bindings.values())

    def snapshot(self) -> ToolSnapshot:
        """Capture an immutable view of definitions and private bindings."""

        return ToolSnapshot(self._bindings)


def runtime_tool(
    *,
    name: str,
    description: str,
    permission: str,
    side_effect: SideEffect = SideEffect.NONE,
    idempotent: bool = False,
    approval: ApprovalRequirement = ApprovalRequirement.FOR_SIDE_EFFECTS,
    timeout_seconds: float | None = None,
) -> Callable[[Callable[..., Awaitable[_T]]], Callable[..., Awaitable[_T]]]:
    """Decorate one fully typed async function as a host-managed tool."""

    def decorate(function: Callable[..., Awaitable[_T]]) -> Callable[..., Awaitable[_T]]:
        """Validate a function and attach private registry metadata."""

        if not inspect.iscoroutinefunction(function):
            raise TypeError("runtime_tool can decorate async functions only")
        try:
            hints = get_type_hints(function)
        except (NameError, TypeError, PydanticUndefinedAnnotation) as exc:
            raise TypeError("tool annotations could not be resolved") from exc
        return_annotation = hints.get("return", inspect.Signature.empty)
        if return_annotation is inspect.Signature.empty or return_annotation is Any:
            raise TypeError("tool return annotation is required")
        input_model = _build_input_model(function, name)
        definition = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_model.model_json_schema(),
            output_schema=_schema_for(return_annotation),
            permission=permission,
            side_effect=side_effect,
            idempotent=idempotent,
            approval=approval,
            timeout_seconds=timeout_seconds,
        )
        output_adapter = TypeAdapter(return_annotation)
        function.__dict__.update(
            {
                "__runtime_tool_definition__": definition,
                "__runtime_tool_input_model__": input_model,
                "__runtime_tool_output_adapter__": output_adapter,
            }
        )
        return function

    return decorate


class ToolExecutor:
    """Execute registered tools through the fixed Phase 5 safety pipeline."""

    def __init__(
        self,
        registry: ToolRegistry | ToolSnapshot,
        *,
        permission_policy: ToolPermissionPolicy | None = None,
        approval_handler: ApprovalHandler | None = None,
        retry_policy: ToolRetryPolicy | None = None,
        failure_policy: ToolFailurePolicy = ToolFailurePolicy.RETURN_ERROR,
        timeout_seconds: float = 30.0,
        approval_timeout_seconds: float = 60.0,
        event_sink: Callable[[RuntimeEvent], Awaitable[Any]] | None = None,
    ) -> None:
        """Configure an in-memory executor with fail-closed defaults."""

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if not math.isfinite(approval_timeout_seconds) or approval_timeout_seconds <= 0:
            raise ValueError("approval_timeout_seconds must be finite and positive")
        self.snapshot = registry if isinstance(registry, ToolSnapshot) else registry.snapshot()
        self.permission_policy = permission_policy or ToolPermissionPolicy()
        self.approval_handler = approval_handler
        self.retry_policy = retry_policy or ToolRetryPolicy()
        self.failure_policy = ToolFailurePolicy(failure_policy)
        self.timeout_seconds = timeout_seconds
        self.approval_timeout_seconds = approval_timeout_seconds
        self.event_sink = event_sink
        self.events: list[RuntimeEvent] = []
        self._calls: dict[tuple[str, str], asyncio.Future[ToolResult]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._sequence = 0

    def end_invocation(self, invocation_id: str) -> None:
        """Release deduplication state after a provider invocation ends."""

        for key in tuple(self._calls):
            if key[0] == invocation_id:
                future = self._calls.pop(key, None)
                if future is not None and not future.done():
                    future.cancel()
        self._locks.pop(invocation_id, None)

    async def execute(self, request: ToolRequest) -> ToolResult:
        """Execute or await one deduplicated tool request."""

        key = (request.invocation_id, request.call_id)
        lock = self._locks.setdefault(request.invocation_id, asyncio.Lock())
        async with lock:
            future = self._calls.get(key)
            owner = future is None
            if owner:
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_consume_future_exception)
                self._calls[key] = future
        assert future is not None
        if not owner:
            return await asyncio.shield(future)
        try:
            result = await self._execute_owner(request)
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            self._calls.pop(key, None)
            raise
        except Exception as exc:
            if self.failure_policy is ToolFailurePolicy.RAISE:
                if not future.done():
                    future.set_exception(exc)
                raise
            result = self._error_result(request, exc)
        if not future.done():
            future.set_result(result)
        return result

    async def invoke(self, request: ToolRequest) -> ToolResult:
        """Alias for adapters that use invocation terminology."""

        return await self.execute(request)

    async def _execute_owner(self, request: ToolRequest) -> ToolResult:
        """Run the validated owner pipeline."""

        started = asyncio.get_running_loop().time()
        binding = self.snapshot._bindings.get(request.name)
        if binding is None:
            await self._emit_request(request, None)
            await self._emit_terminal(
                request, None, RuntimeEventKind.TOOL_FAILED, 0, error_code="tool_execution_error"
            )
            raise ToolExecutionError("Unknown tool", details={"tool_name": request.name})
        definition = binding.definition
        await self._emit_request(request, definition)
        try:
            validated = binding.input_model.model_validate(_thaw(request.arguments))
        except Exception as exc:
            await self._emit(RuntimeEventKind.VALIDATION_FAILED, request, definition, 0)
            await self._emit_terminal(
                request, definition, RuntimeEventKind.TOOL_FAILED, 0, error_code="tool_execution_error"
            )
            raise ToolExecutionError(
                "Tool arguments failed validation", details={"tool_name": definition.name}
            ) from exc
        if not self.permission_policy.allows(definition.permission):
            await self._emit_terminal(
                request, definition, RuntimeEventKind.TOOL_DENIED, 0,
                error_code="tool_denied", denied=True,
            )
            raise ToolDeniedError("Tool permission denied", details={"tool_name": definition.name})
        if self._requires_approval(definition):
            await self._emit(RuntimeEventKind.TOOL_APPROVAL_REQUESTED, request, definition, 0)
            decision = await self._approval(request, definition, validated)
            await self._emit(
                RuntimeEventKind.TOOL_APPROVAL_RESOLVED,
                request,
                definition,
                0,
                payload={"decision": decision.value},
            )
            if decision is not ApprovalDecision.APPROVE:
                await self._emit_terminal(
                    request, definition, RuntimeEventKind.TOOL_DENIED, 0,
                    error_code="tool_denied", denied=True,
                )
                raise ToolDeniedError(
                    "Tool approval denied", details={"tool_name": definition.name}
                )
        if self.retry_policy.max_attempts > 1 and not definition.idempotent:
            await self._emit_terminal(
                request, definition, RuntimeEventKind.TOOL_FAILED, 0,
                error_code="tool_execution_error",
            )
            raise ToolExecutionError(
                "Retry policy is incompatible with a non-idempotent tool",
                details={"tool_name": definition.name, "attempts": 0},
            )
        max_attempts = self.retry_policy.max_attempts
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            await self._emit(RuntimeEventKind.TOOL_STARTED, request, definition, attempt)
            try:
                output = await asyncio.wait_for(
                    binding.function(
                        **{
                            field_name: getattr(validated, field_name)
                            for field_name in type(validated).model_fields
                        }
                    ),
                    timeout=definition.timeout_seconds or self.timeout_seconds,
                )
                try:
                    output = binding.output_adapter.validate_python(output)
                    serialized_output = binding.output_adapter.dump_python(output, mode="json")
                    frozen_output = _json_safe(serialized_output)
                except Exception as exc:
                    raise _OutputValidationError(
                        "Tool output failed validation", details={"tool_name": definition.name}
                    ) from exc
                result = ToolResult(
                    request.invocation_id,
                    request.call_id,
                    definition.name,
                    True,
                    frozen_output,
                    attempts=attempt,
                    duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                )
                await self._emit(
                    RuntimeEventKind.TOOL_COMPLETED,
                    request,
                    definition,
                    attempt,
                    payload={"arguments": validated.model_dump(mode="json"), "result": _thaw(frozen_output)},
                    duration_ms=(asyncio.get_running_loop().time() - started) * 1000,
                    success=True,
                )
                return result
            except TimeoutError:
                last_error = ToolExecutionError(
                    "Tool execution timed out",
                    details={"tool_name": definition.name, "timed_out": True},
                )
            except asyncio.CancelledError:
                raise
            except _OutputValidationError as exc:
                last_error = exc
                await self._emit_terminal(
                    request, definition, RuntimeEventKind.TOOL_FAILED, attempt,
                    error_code="tool_execution_error",
                )
                raise
            except ToolExecutionError as exc:
                last_error = exc
            except Exception:
                last_error = ToolExecutionError(
                    "Tool execution failed", details={"tool_name": definition.name}
                )
            if attempt < max_attempts:
                await self._emit(
                    RuntimeEventKind.TOOL_RETRY_SCHEDULED,
                    request,
                    definition,
                    attempt,
                    payload={"next_attempt": attempt + 1},
                )
        assert last_error is not None
        await self._emit_terminal(
            request,
            definition,
            RuntimeEventKind.TOOL_FAILED,
            max_attempts,
            error_code="retry_exhausted" if max_attempts > 1 else "tool_execution_error",
            timed_out=isinstance(last_error, ToolExecutionError)
            and bool(getattr(last_error, "details", {}).get("timed_out", False)),
        )
        if max_attempts > 1:
            raise RetryExhaustedError(
                "Tool retries exhausted",
                details={"tool_name": definition.name, "attempts": max_attempts},
            ) from last_error
        raise last_error

    def _requires_approval(self, definition: ToolDefinition) -> bool:
        """Evaluate approval requirement from the declared side effect."""

        return definition.approval is ApprovalRequirement.ALWAYS or (
            definition.approval is ApprovalRequirement.FOR_SIDE_EFFECTS
            and definition.side_effect in {SideEffect.WRITE, SideEffect.DESTRUCTIVE}
        )

    async def _approval(
        self, request: ToolRequest, definition: ToolDefinition, validated: BaseModel
    ) -> ApprovalDecision:
        """Run the optional approval callback fail-closed."""

        if self.approval_handler is None:
            return ApprovalDecision.DENY
        approval_request = ApprovalRequest(
            request.invocation_id,
            request.call_id,
            definition.name,
            definition.permission,
            definition.side_effect,
            validated.model_dump(mode="json"),
        )
        task = asyncio.create_task(self.approval_handler.request_approval(approval_request))
        try:
            decision = await asyncio.wait_for(asyncio.shield(task), timeout=self.approval_timeout_seconds)
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                task.cancel()
                raise
            return ApprovalDecision.DENY
        except (TimeoutError, Exception):
            task.cancel()
            return ApprovalDecision.DENY
        finally:
            if not task.done():
                task.cancel()
        return decision if isinstance(decision, ApprovalDecision) else ApprovalDecision.DENY

    async def _emit_request(
        self, request: ToolRequest, definition: ToolDefinition | None
    ) -> None:
        """Emit the first causal event for every provider request."""

        await self._emit(
            RuntimeEventKind.TOOL_REQUESTED,
            request,
            definition,
            0,
            payload={"arguments": _thaw(request.arguments)},
        )

    async def _emit_terminal(
        self,
        request: ToolRequest,
        definition: ToolDefinition | None,
        kind: RuntimeEventKind,
        attempt: int,
        *,
        error_code: str | None = None,
        denied: bool = False,
        timed_out: bool = False,
    ) -> None:
        """Emit one sanitized terminal event for a request."""

        await self._emit(
            kind,
            request,
            definition,
            attempt,
            success=kind is RuntimeEventKind.TOOL_COMPLETED,
            error_code=error_code,
            denied=denied,
            timed_out=timed_out,
        )

    async def _emit(
        self,
        kind: RuntimeEventKind,
        request: ToolRequest,
        definition: ToolDefinition | None,
        attempt: int,
        *,
        payload: Mapping[str, Any] | None = None,
        duration_ms: float | None = None,
        success: bool | None = None,
        error_code: str | None = None,
        denied: bool = False,
        timed_out: bool = False,
    ) -> None:
        """Emit a redacted neutral tool event."""

        self._sequence += 1
        event = RuntimeEvent(
            kind=kind,
            event_id=f"{request.invocation_id}:{self._sequence}",
            sequence=self._sequence,
            occurred_at=datetime.now(UTC),
            runtime=RuntimeIdentity("proteo-runtime", "host-tools"),
            invocation_id=request.invocation_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            metadata={
                "tool_name": definition.name if definition is not None else request.name,
                "tool_call_id": request.call_id,
                "permission": definition.permission if definition is not None else "",
                "side_effect": definition.side_effect.value if definition is not None else "none",
                "attempt": attempt,
                "duration_ms": duration_ms or 0.0,
                **({"success": success} if success is not None else {}),
                **({"error_code": error_code} if error_code else {}),
                **({"denied": True} if denied else {}),
                **({"timed_out": True} if timed_out else {}),
            },
            payload=payload or {},
        )
        self.events.append(event)
        if self.event_sink is not None:
            await self.event_sink(event)

    def _error_result(self, request: ToolRequest, exc: Exception) -> ToolResult:
        """Convert an internal failure into a stable model-facing result."""

        code = getattr(exc, "code", "tool_execution_error")
        denied = isinstance(exc, ToolDeniedError)
        timed_out = bool(getattr(exc, "details", {}).get("timed_out", False))
        attempts = int(getattr(exc, "details", {}).get("attempts", 1))
        return ToolResult(
            request.invocation_id,
            request.call_id,
            request.name,
            False,
            {"error": str(code)},
            error_code=str(code),
            attempts=attempts,
            denied=denied,
            timed_out=timed_out,
        )


def _consume_future_exception(future: asyncio.Future[ToolResult]) -> None:
    """Consume an owner exception when no duplicate waiter is present."""

    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.InvalidStateError:
        return
