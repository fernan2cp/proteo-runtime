"""Local SQLite event observer and observability configuration for Smart Quote Agent."""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import Any

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from langsmith_recording import RecordingLangSmithClient  # noqa: E402
from otel_recording import (  # noqa: E402
    LocalOtelBundle,
    create_local_otel_bundle,
)
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
        self.flush_count = 0
        self.close_count = 0
        self.failure_count = 0

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

    @property
    def is_closed(self) -> bool:
        """Return whether the observer has been closed.

        Returns:
            True if closed, False otherwise.
        """
        return self._closed

    def record_failure(self, error: Any) -> None:
        """Record an observer execution failure for diagnostics.

        Args:
            error: The error or observer type that failed.
        """
        self.failure_count += 1

    async def flush(self) -> None:
        """Flush pending writes (no-op as writes are synchronous per operation)."""
        self.flush_count += 1

    async def close(self) -> None:
        """Release observer resources idempotently."""
        if self._closed:
            return
        self.close_count += 1
        self._closed = True


class NonOwningObserver(RuntimeObserver):
    """Observer adapter delegating on_event while leaving close/flush ownership to the host."""

    def __init__(self, target: RuntimeObserver) -> None:
        """Initialize adapter around target observer.

        Args:
            target: Underlying RuntimeObserver instance.
        """
        self.target = target

    async def on_event(self, event: RuntimeEvent) -> None:
        """Forward projected event to the underlying observer.

        Args:
            event: Projected RuntimeEvent.
        """
        await self.target.on_event(event)

    async def flush(self) -> None:
        """No-op: lifecycle is owned exclusively by the host application."""
        pass

    async def close(self) -> None:
        """No-op: lifecycle is owned exclusively by the host application."""
        pass

    def record_failure(self, observer_type: str) -> None:
        """Forward failure recording if supported by the target observer.

        Args:
            observer_type: Identifier of the failing observer.
        """
        if hasattr(self.target, "record_failure"):
            with contextlib.suppress(Exception):
                self.target.record_failure(observer_type)

    def __repr__(self) -> str:
        """Return developer-friendly string representation.

        Returns:
            String naming the target observer.
        """
        return f"NonOwningObserver({self.target!r})"


class ObservabilityManager:
    """Manages application observability lifecycle, event bus, and provider resources."""

    def __init__(
        self,
        mode: str | None = None,
        db_path: Path | str | None = None,
    ) -> None:
        """Initialize observability components according to requested mode.

        Args:
            mode: Observability mode ('local', 'off', or 'local+langsmith').
            db_path: Path to the telemetry database.

        Raises:
            ValueError: If mode is unsupported.
        """
        effective_mode = (
            os.environ.get("DEMO_OBSERVABILITY", "local").strip().lower()
            if mode is None
            else mode.strip().lower()
        )
        if effective_mode not in ("local", "off", "local+langsmith"):
            raise ValueError(
                f"Unsupported observability mode: {effective_mode!r}. "
                "Supported modes: 'local', 'off', 'local+langsmith'."
            )

        self.mode = effective_mode
        self.db_path = get_telemetry_db_path(db_path)
        self._closed = False

        if self.mode == "off":
            self.otel_bundle: LocalOtelBundle | None = None
            self.sqlite_obs: SQLiteEventObserver | None = None
            self.ls_client: RecordingLangSmithClient | None = None
            self.ls_obs: LangSmithObserver | None = None
            self.otel_obs: OpenTelemetryObserver | None = None
            self.real_ls_obs: LangSmithObserver | None = None
            self.app_config = ObservabilityConfig(observers=(), strict=False)
            self.runtime_config = ObservabilityConfig(observers=(), strict=False)
            self.bus = RuntimeEventBus(self.app_config)
            return

        # 1. Initialize local observers and clients
        self.sqlite_obs = SQLiteEventObserver(self.db_path)
        self.ls_client = RecordingLangSmithClient(self.db_path)
        self.ls_obs = LangSmithObserver(
            client=self.ls_client,
            project_name="proteo-smart-quote-demo",
            owns_client=False,
        )

        # 2. Initialize OTel bundle and observer
        self.otel_bundle = create_local_otel_bundle(self.db_path)
        tracer = self.otel_bundle.tracer_provider.get_tracer("proteo.smart_quote_agent")
        meter = self.otel_bundle.meter_provider.get_meter("proteo.smart_quote_agent")
        self.otel_obs = OpenTelemetryObserver(tracer=tracer, meter=meter)

        # Attach observer to exporters for failure diagnosis and degradation tracking
        self.otel_bundle.span_exporter.set_observer(self.otel_obs)
        self.otel_bundle.metric_exporter.set_observer(self.otel_obs)

        # 3. Build owner bindings for application bus
        app_bindings: list[ObserverBinding] = [
            ObserverBinding(self.sqlite_obs, PayloadMode.METADATA_ONLY),
            ObserverBinding(self.ls_obs, PayloadMode.METADATA_ONLY),
            ObserverBinding(self.otel_obs, PayloadMode.METADATA_ONLY),
        ]
        if self.mode == "local+langsmith":
            self.real_ls_obs = LangSmithObserver(project_name="proteo-smart-quote-demo")
            app_bindings.append(ObserverBinding(self.real_ls_obs, PayloadMode.METADATA_ONLY))
        else:
            self.real_ls_obs = None

        self.app_config = ObservabilityConfig(observers=tuple(app_bindings), strict=False)
        self.bus = RuntimeEventBus(self.app_config)

        # 4. Build borrowed bindings for CodexRuntime with NonOwningObserver wrappers
        runtime_bindings: list[ObserverBinding] = [
            ObserverBinding(NonOwningObserver(self.sqlite_obs), PayloadMode.METADATA_ONLY),
            ObserverBinding(NonOwningObserver(self.ls_obs), PayloadMode.METADATA_ONLY),
            ObserverBinding(NonOwningObserver(self.otel_obs), PayloadMode.METADATA_ONLY),
        ]
        if self.real_ls_obs is not None:
            runtime_bindings.append(
                ObserverBinding(NonOwningObserver(self.real_ls_obs), PayloadMode.METADATA_ONLY)
            )

        self.runtime_config = ObservabilityConfig(observers=tuple(runtime_bindings), strict=False)

    async def flush(self) -> None:
        """Flush all telemetry observers and OpenTelemetry providers idempotently."""
        if self._closed:
            return
        await self.bus.flush()
        if self.otel_bundle is not None:
            self.otel_bundle.force_flush()

    async def close(self) -> None:
        """Flush and close all telemetry components and providers idempotently."""
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self.bus.close()
        if self.otel_bundle is not None:
            with contextlib.suppress(Exception):
                self.otel_bundle.force_flush()
            with contextlib.suppress(Exception):
                self.otel_bundle.shutdown()


def create_observability_manager(
    mode: str | None = None,
    db_path: Path | str | None = None,
) -> ObservabilityManager:
    """Create and configure a unified ObservabilityManager.

    Args:
        mode: Observability mode ('local', 'off', or 'local+langsmith').
        db_path: Path to the SQLite telemetry database.

    Returns:
        Configured ObservabilityManager instance.
    """
    return ObservabilityManager(mode=mode, db_path=db_path)


def create_observability_config(
    mode: str | None = None,
    db_path: Path | str | None = None,
    *,
    non_owning: bool = False,
) -> ObservabilityConfig:
    """Create an ObservabilityConfig configured for the requested mode.

    Args:
        mode: Observability mode ('local', 'off', or 'local+langsmith'). Defaults to
            the DEMO_OBSERVABILITY environment variable, falling back to 'local'.
        db_path: Path to the SQLite telemetry database. Defaults to DEFAULT_TELEMETRY_DB_PATH.
        non_owning: When True, wrap observers in NonOwningObserver for safe borrowing by CodexRuntime.

    Returns:
        Configured ObservabilityConfig instance with strict=False and METADATA_ONLY policy.
    """
    mgr = ObservabilityManager(mode=mode, db_path=db_path)
    return mgr.runtime_config if non_owning else mgr.app_config


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
