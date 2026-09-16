"""Configuration schema tests."""

import operator
from typing import Any, cast

import pytest

from proteo_runtime.config import RuntimeConfigV1, validate_config
from proteo_runtime.core.errors import ConfigurationError


def _payload() -> dict[str, object]:
    """Return a valid version-one configuration payload."""

    return {
        "schema_version": 1,
        "runtime": "fake",
        "profiles": {"brain": {"low": {"model": "fake", "reasoning_effort": "low"}}},
    }


def test_valid_config_is_frozen_and_lookup_is_pure() -> None:
    """Valid configuration loads with immutable nested mappings."""

    config = validate_config(_payload())
    assert isinstance(config, RuntimeConfigV1)
    assert config.lookup("brain", "low").model == "fake"
    with pytest.raises(TypeError):
        operator.setitem(cast(Any, config.profiles), "new", {})


def test_invalid_keys_versions_and_missing_mappings_raise_path_errors() -> None:
    """Unknown keys, versions, and missing combinations never silently fallback."""

    with pytest.raises(ConfigurationError):
        validate_config({**_payload(), "unexpected": True})
    with pytest.raises(ConfigurationError):
        validate_config({**_payload(), "schema_version": 2})
    config = validate_config(_payload())
    with pytest.raises(ConfigurationError, match="profiles.brain.high"):
        config.lookup("brain", "high")


def test_packaged_defaults_resolve_controlled_agent_all_logical_levels() -> None:
    """Packaged default configuration resolves controlled_agent across all logical levels."""
    from proteo_runtime.config import load_runtime_config
    from proteo_runtime.core.profiles import LogicalLevel

    config = load_runtime_config()
    for level in LogicalLevel:
        mapping = config.lookup("controlled_agent", level)
        assert mapping.model
        assert mapping.reasoning_effort
