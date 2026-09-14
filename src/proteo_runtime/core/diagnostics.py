"""Diagnostic value objects."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .types import freeze_mapping


class DiagnosticSeverity(StrEnum):
    """Severity assigned to a runtime diagnostic."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RuntimeDiagnostic:
    """Immutable safe diagnostic emitted with a runtime result."""

    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.INFO
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze details and reject credential-shaped fields."""

        if not self.code or not self.message:
            raise ValueError("Diagnostic code and message are required")
        object.__setattr__(self, "details", freeze_mapping(self.details))
