"""Shared test configuration."""


def pytest_configure(config: object) -> None:
    """Register the integration marker without loading provider SDKs."""

    config.addinivalue_line("markers", "integration: external provider tests")  # type: ignore[attr-defined]
