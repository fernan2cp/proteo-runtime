"""Configuration validation entry points."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from proteo_runtime.core.errors import ConfigurationError

from .models import RuntimeConfigV1


def validate_config(payload: Mapping[str, Any]) -> RuntimeConfigV1:
    """Validate a mapping and normalize Pydantic errors to ConfigurationError."""

    try:
        return RuntimeConfigV1.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "$"
        del exc
        raise ConfigurationError("Invalid runtime configuration", path=location) from None
