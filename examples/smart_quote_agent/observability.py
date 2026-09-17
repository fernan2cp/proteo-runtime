"""Local SQLite event observer and observability configuration for Smart Quote Agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from langsmith_recording import RecordingLangSmithClient  # noqa: E402
from otel_recording import create_local_otel_providers  # noqa: E402
from telemetry_db import get_telemetry_db_path, insert_runtime_event  # noqa: E402

from proteo_runtime.core.events import RuntimeEvent  # noqa: E402
from proteo_runtime.observability import (  # noqa: E402
    ObservabilityConfig,
    ObserverBinding,
    PayloadMode,
    RuntimeEventBus,
    RuntimeObserver,
)
from proteo_runtime.observability.langsmith import LangSmithObserver  # noqa: E402
from proteo_runtime.observability.opentelemetry import OpenTelemetryObserver  # noqa: E402


class SQLiteEventObserver(RuntimeObserver):
    """Local SQLite observer persisting neutral Proteo RuntimeEvents."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize the observer with an optional telemetry database path.

        Args:
            db_path: Target SQLite database path, defaulting to DEFAULT_TELEMETRY_DB_PATH.
        """
        self.db_path = get_telemetry_db_path(db_path)
        self._closed = False

    async def on_event(self, event: RuntimeEvent) -> None:
        """Process one projected runtime event and persist it into runtime_events.

        Args:
            event: Projected RuntimeEvent delivered from the neutral event bus.
        """
        if self._closed:
            return

        event_kind = event.kind.value if hasattr(event.kind, "value") else str(event.kind)
        occurred_at = (
            event.occurred_at.isoformat()
            if hasattr(event.occurred_at, "isoformat")
            else str(event.occurred_at)
        )

        metadata = dict(event.metadata) if event.metadata else {}

        # Extract useful scalar attributes from metadata per Guide §9
        runtime_name = getattr(event, "runtime", None) or metadata.get("proteo.runtime")
        model = metadata.get("proteo.model") or metadata.get("model")
        profile = metadata.get("proteo.profile") or metadata.get("profile")
        reasoning_effort = metadata.get("proteo.reasoning_effort") or metadata.get(
            "reasoning_effort"
        )
        tool_name = metadata.get("tool_name") or metadata.get("name")
        tool_call_id = metadata.get("tool_call_id")
        status = metadata.get("status")

        duration_val = metadata.get("proteo.latency_ms") or metadata.get("duration_ms")
        duration_ms = float(duration_val) if duration_val is not None else None

        insert_runtime_event(
            self.db_path,
            event_id=event.event_id,
            event_kind=event_kind,
            occurred_at=occurred_at,
            invocation_id=event.invocation_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            runtime_name=str(runtime_name) if runtime_name is not None else None,
            model=str(model) if model is not None else None,
            profile=str(profile) if profile is not None else None,
            reasoning_effort=str(reasoning_effort) if reasoning_effort is not None else None,
            tool_name=str(tool_name) if tool_name is not None else None,
            tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
            status=str(status) if status is not None else None,
            duration_ms=duration_ms,
            metadata=metadata,
        )

    async def flush(self) -> None:
        """Flush pending writes (no-op as writes are synchronous per operation)."""
        pass

    async def close(self) -> None:
        """Release observer resources idempotently."""
        self._closed = True


def create_observability_config(
    mode: str | None = None,
    db_path: Path | str | None = None,
) -> ObservabilityConfig:
    """Create an ObservabilityConfig configured for the requested mode.

    Args:
        mode: Observability mode ('local', 'off', or 'local+langsmith'). Defaults to
            the DEMO_OBSERVABILITY environment variable, falling back to 'local'.
        db_path: Path to the SQLite telemetry database. Defaults to DEFAULT_TELEMETRY_DB_PATH.

    Returns:
        Configured ObservabilityConfig instance with strict=False and METADATA_ONLY policy.

    Raises:
        ValueError: If mode is not one of 'local', 'off', or 'local+langsmith'.
    """
    effective_mode = (
        os.environ.get("DEMO_OBSERVABILITY", "local").strip().lower()
        if mode is None
        else mode.strip().lower()
    )

    if effective_mode == "off":
        return ObservabilityConfig(observers=(), strict=False)

    if effective_mode not in ("local", "local+langsmith"):
        raise ValueError(
            f"Unsupported observability mode: {effective_mode!r}. "
            "Supported modes: 'local', 'off', 'local+langsmith'."
        )

    target_db = get_telemetry_db_path(db_path)
    sqlite_obs = SQLiteEventObserver(target_db)
    ls_client = RecordingLangSmithClient(target_db)
    ls_obs = LangSmithObserver(
        client=ls_client,
        project_name="proteo-smart-quote-demo",
        owns_client=False,
    )
    tracer_provider, meter_provider = create_local_otel_providers(target_db)
    tracer = tracer_provider.get_tracer("proteo.smart_quote_agent")
    meter = meter_provider.get_meter("proteo.smart_quote_agent")
    otel_obs = OpenTelemetryObserver(tracer=tracer, meter=meter)

    bindings: list[ObserverBinding] = [
        ObserverBinding(sqlite_obs, PayloadMode.METADATA_ONLY),
        ObserverBinding(ls_obs, PayloadMode.METADATA_ONLY),
        ObserverBinding(otel_obs, PayloadMode.METADATA_ONLY),
    ]

    if effective_mode == "local+langsmith":
        real_ls_obs = LangSmithObserver(project_name="proteo-smart-quote-demo")
        bindings.append(ObserverBinding(real_ls_obs, PayloadMode.METADATA_ONLY))

    return ObservabilityConfig(observers=tuple(bindings), strict=False)


def get_observability_bus(
    config: ObservabilityConfig | None = None,
) -> RuntimeEventBus:
    """Return a RuntimeEventBus initialized with the provided or default observability config.

    Args:
        config: Optional ObservabilityConfig. Defaults to create_observability_config().

    Returns:
        RuntimeEventBus instance ready for event emission.
    """
    return RuntimeEventBus(config or create_observability_config())
