"""Quota-safety and provider-isolation contract tests."""

import asyncio
import builtins
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from proteo_runtime import RuntimeInput
from proteo_runtime.testing import FakeRuntime, FakeTurn


@pytest.mark.asyncio
async def test_default_runtime_operations_are_provider_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle, invocation, streaming, and sessions cannot access external services."""

    forbidden_imports = ("openai_codex", "langgraph", "langsmith", "opentelemetry")
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        """Reject imports of provider SDKs and integrations."""

        if any(name == item or name.startswith(item + ".") for item in forbidden_imports):
            raise AssertionError(f"Forbidden provider import: {name}")
        return original_import(name, *args, **kwargs)

    def fail_external(*args: Any, **kwargs: Any) -> Any:
        """Fail if code attempts network or process access."""

        del args, kwargs
        raise AssertionError("External side effect attempted")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(socket.socket, "connect", fail_external)
    monkeypatch.setattr(socket, "create_connection", fail_external)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, fail_external)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_external)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", fail_external)
    original_getenv = os.getenv
    original_env_get = os.environ.get

    def guarded_getenv(key: str, default: str | None = None) -> str | None:
        """Reject reads of credential-shaped environment variables."""

        if any(token in key.casefold() for token in ("openai", "codex", "api_key", "token")):
            raise AssertionError(f"Credential environment variable accessed: {key}")
        return original_getenv(key, default)

    def guarded_env_get(key: str, default: str | None = None) -> str | None:
        """Reject mapping reads of credential-shaped environment variables."""

        if any(token in key.casefold() for token in ("openai", "codex", "api_key", "token")):
            raise AssertionError(f"Credential environment variable accessed: {key}")
        return original_env_get(key, default)

    monkeypatch.setattr(os, "getenv", guarded_getenv)
    monkeypatch.setattr(os.environ, "get", guarded_env_get)

    original_open = Path.open
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def guarded_path(path: Path) -> bool:
        """Identify credential-shaped paths while allowing normal source reads."""

        lowered = str(path).casefold()
        return any(token in lowered for token in (".codex", "auth.json", ".openai", "credentials"))

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        """Reject credential file access."""

        if guarded_path(path):
            raise AssertionError(f"Credential path accessed: {path}")
        return cast(Any, original_open)(path, *args, **kwargs)

    def guarded_read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        """Reject credential text reads."""

        if guarded_path(path):
            raise AssertionError(f"Credential path accessed: {path}")
        return cast(str, cast(Any, original_read_text)(path, *args, **kwargs))

    def guarded_read_bytes(path: Path, *args: Any, **kwargs: Any) -> bytes:
        """Reject credential binary reads."""

        if guarded_path(path):
            raise AssertionError(f"Credential path accessed: {path}")
        return cast(bytes, cast(Any, original_read_bytes)(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    runtime = FakeRuntime(
        turns=[FakeTurn(value="isolated"), FakeTurn(value="streamed"), FakeTurn(value="after")]
    )
    await runtime.start()
    assert (
        await runtime.model(profile="brain").ainvoke(RuntimeInput.from_value("input"))
    ).value == "isolated"
    session = await runtime.session()
    events = [event async for event in session.astream(RuntimeInput.from_value("input"))]
    assert events
    assert (await session.ainvoke(RuntimeInput.from_value("next"))).value == "after"
    await session.close()
    await runtime.close()
    assert "openai_codex" not in sys.modules
