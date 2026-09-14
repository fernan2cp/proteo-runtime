"""CLI contract tests."""

import pytest

from proteo_runtime.cli.main import main


def test_cli_help_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI can print help without initializing a provider."""

    assert main([]) == 0
    assert "Proteo Runtime" in capsys.readouterr().out


def test_cli_version_uses_package_version() -> None:
    """The version action exits cleanly with the package version."""

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
