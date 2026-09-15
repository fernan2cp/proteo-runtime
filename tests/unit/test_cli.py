"""CLI contract tests."""

import runpy
import sys

import pytest

from proteo_runtime.cli.main import main


def test_cli_help_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI can print help without initializing a provider."""

    assert main([]) == 0
    assert "Proteo Runtime" in capsys.readouterr().out


def test_cli_version_uses_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    """The version action exits cleanly with the package version."""

    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.5.0"


def test_module_entrypoint_runs_without_provider_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``python -m`` entrypoint delegates to the provider-free CLI."""

    monkeypatch.setattr(sys, "argv", ["proteo_runtime", "--version"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("proteo_runtime", run_name="__main__")
    assert exc.value.code == 0
