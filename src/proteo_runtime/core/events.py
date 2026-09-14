"""Typed runtime event envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .identity import RuntimeIdentity
from .types import freeze_mapping


class RuntimeEventKind(StrEnum):
    """Kinds emitted during lifecycle, invocation, and session operations."""

    RUNTIME_STARTED = "runtime_started"
    RUNTIME_STOPPED = "runtime_stopped"
    INVOCATION_STARTED = "invocation_started"
    INVOCATION_COMPLETED = "invocation_completed"
    INVOCATION_FAILED = "invocation_failed"
    SESSION_CREATED = "session_created"
    SESSION_RESUMED = "session_resumed"
    TURN_STARTED = "turn_started"
    TURN_COMPLETED = "turn_completed"
    OUTPUT_TEXT_DELTA = "output_text_delta"
    TOKEN_USAGE_UPDATED = "token_usage_updated"
    TOOL_REQUESTED = "tool_requested"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    RETRY_SCHEDULED = "retry_scheduled"
    VALIDATION_FAILED = "validation_failed"
    CAPABILITY_REJECTED = "capability_rejected"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Immutable event envelope with correlation identifiers."""

    kind: RuntimeEventKind
    event_id: str
    sequence: int
    occurred_at: datetime
    runtime: RuntimeIdentity
    invocation_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate sequencing and normalize timestamps and metadata."""

        if self.sequence < 0 or not self.event_id:
            raise ValueError("Event id and non-negative sequence are required")
        timestamp = self.occurred_at
        if timestamp.tzinfo is None:
            raise ValueError("Event timestamp must be timezone-aware")
        object.__setattr__(self, "occurred_at", timestamp.astimezone(UTC))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
