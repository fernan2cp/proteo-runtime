"""Shared test configuration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register the integration marker without loading provider SDKs."""

    config.addinivalue_line("markers", "integration: external provider tests")
