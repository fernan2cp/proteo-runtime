"""Privacy and correlation tests for host-side turn error diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from error_diagnostics import sanitize_exception
from observability import ObservabilityManager
from telemetry_db import fetch_interaction_events

from proteo_runtime.core.errors import RuntimeUnavailableError


class SimulatedProviderError(RuntimeError):
    """Provider-shaped error carrying a machine-readable stable code."""

    error_code = "provider.transport_timeout"


def test_external_traceback_path_is_reduced_to_its_basename(tmp_path: Path) -> None:
    """Remove absolute external paths and exception text from a diagnostic summary."""
    provider_path = r"C:\Users\sensitive-user\provider\transport.py"
    try:
        exec(compile("raise RuntimeError('private exception content')", provider_path, "exec"), {})
    except RuntimeError as error:
        summary = sanitize_exception(
            error,
            repository_root=tmp_path,
        )

    summary_json = json.dumps(summary)
    assert "<external>/transport.py" in summary_json
    assert "sensitive-user" not in summary_json
    assert "private exception content" not in summary_json


def test_provider_failure_metadata_is_allowlisted_and_text_is_redacted(tmp_path: Path) -> None:
    """Retain safe provider classification while excluding arbitrary error details."""
    error = RuntimeUnavailableError(
        "sensitive provider message",
        details={
            "provider_status": "failed",
            "provider_error_code": "responseStreamDisconnected",
            "provider_http_status": 400,
            "message": "sensitive message field",
            "additional_details": "sensitive additional details",
            "unexpected": "must not be copied",
        },
    )

    summary = sanitize_exception(error, repository_root=tmp_path)
    summary_json = json.dumps(summary)

    assert summary["provider_status"] == "failed"
    assert summary["provider_error_code"] == "responseStreamDisconnected"
    assert summary["provider_http_status"] == 400
    assert "sensitive provider message" not in summary_json
    assert "sensitive message field" not in summary_json
    assert "sensitive additional details" not in summary_json
    assert "must not be copied" not in summary_json


@pytest.mark.asyncio
async def test_host_error_is_correlated_and_excludes_exception_messages(tmp_path: Path) -> None:
    """Persist exception type, cause chain, and sanitized frames without messages."""
    database_path = tmp_path / "error_diagnostics.sqlite3"
    manager = ObservabilityManager(mode="local", db_path=database_path)
    try:
        try:
            raise ValueError("sensitive-cause-message")
        except ValueError as cause:
            try:
                raise SimulatedProviderError("sensitive-provider-message") from cause
            except SimulatedProviderError as error:
                manager.record_host_error(
                    error,
                    stage="quote_planner",
                    interaction_id="interaction-error-test",
                    task_id="task-error-test",
                    workflow_id="quote-error-test",
                )
    finally:
        await manager.close()

    events = fetch_interaction_events(database_path, "interaction-error-test")
    assert len(events) == 1
    event = events[0]
    assert event["event_kind"] == "host.turn_error"
    assert event["status"] == "failed"
    assert event["task_id"] == "task-error-test"
    assert event["interaction_id"] == "interaction-error-test"

    metadata_json = str(event["metadata_json"])
    metadata = json.loads(metadata_json)
    assert metadata["stage"] == "quote_planner"
    assert metadata["exception_module"] == __name__
    assert metadata["exception_type"] == "SimulatedProviderError"
    assert metadata["code"] == "provider.transport_timeout"
    assert metadata["cause_types"] == ["builtins.ValueError"]
    assert metadata["frames"]
    assert metadata["frames"][-1]["file"].endswith(
        "examples/smart_quote_agent/tests/test_host_error_diagnostics.py"
    )
    assert "sensitive-cause-message" not in metadata_json
    assert "sensitive-provider-message" not in metadata_json
    assert "locals" not in metadata_json
