"""Shared immutable and JSON-compatible value helpers."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TypeAlias

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

_SECRET_WORDS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


def is_secret_key(key: str) -> bool:
    """Return whether a metadata key has credential-shaped semantics."""

    normalized = key.casefold().replace("-", "_")
    parts = set(normalized.split("_"))
    return normalized in _SECRET_WORDS or bool(
        parts & {"token", "secret", "password", "credential", "authorization", "apikey"}
    )


def freeze_value(value: object) -> object:
    """Recursively convert common containers to immutable equivalents."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        frozen = {str(key): freeze_value(item) for key, item in value.items()}
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_value(item) for item in value)
    raise TypeError(f"Unsupported metadata value type: {type(value).__name__}")


def freeze_mapping(mapping: Mapping[str, object] | None = None) -> Mapping[str, object]:
    """Return a recursively immutable and secret-free metadata mapping."""

    values = {} if mapping is None else mapping
    for key in values:
        if is_secret_key(str(key)):
            raise ValueError(f"Secret-shaped metadata key is not permitted: {key}")
    frozen = {str(key): freeze_value(value) for key, value in values.items()}
    return MappingProxyType(frozen)
