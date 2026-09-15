"""Configuration source loading and precedence helpers."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from importlib.resources import files
from os import PathLike
from pathlib import Path
from typing import Any

from proteo_runtime.core.errors import ConfigurationError

from .models import RuntimeConfigV1
from .validation import validate_config


def _read_json(path: PathLike[str] | str) -> Mapping[str, Any]:
    """Read one UTF-8 JSON object and normalize filesystem/parser failures."""

    try:
        text = Path(os.fspath(path)).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError("Unable to read runtime configuration", path="$") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("Invalid runtime configuration JSON", path="$") from exc
    if not isinstance(payload, Mapping):
        raise ConfigurationError("Runtime configuration must be a JSON object", path="$")
    return payload


def _packaged_defaults() -> Mapping[str, Any]:
    """Read the packaged Codex version-one defaults."""

    try:
        resource = files("proteo_runtime.config").joinpath("defaults", "codex_v1.json")
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Packaged runtime defaults are invalid", path="$") from exc
    if not isinstance(payload, Mapping):
        raise ConfigurationError("Packaged runtime defaults must be a JSON object", path="$")
    return payload


def load_runtime_config(
    *,
    config_path: PathLike[str] | str | None = None,
    config: RuntimeConfigV1 | None = None,
) -> RuntimeConfigV1:
    """Load the typed runtime configuration using explicit source precedence."""

    if config is not None:
        return config
    selected_path = (
        config_path if config_path is not None else os.environ.get("PROTEO_RUNTIME_CONFIG")
    )
    payload = _read_json(selected_path) if selected_path else _packaged_defaults()
    return validate_config(payload)
