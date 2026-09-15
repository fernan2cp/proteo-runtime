"""Demonstrate secret-safe metadata-only observability with Codex."""

from __future__ import annotations

from proteo_runtime.core.events import RuntimeEvent
from proteo_runtime.observability import (
    ObservabilityConfig,
    ObserverBinding,
    PayloadMode,
)
from proteo_runtime.providers.codex import CodexRuntime


class MetadataObserver:
    """Small host-owned observer that prints event kinds and correlation metadata."""

    async def on_event(self, event: RuntimeEvent) -> None:
        """Print only the projected metadata envelope."""

        print(event.kind.value, dict(event.metadata))

    async def flush(self) -> None:
        """Provide an idempotent flush hook."""

    async def close(self) -> None:
        """Provide an idempotent close hook."""


async def main() -> None:
    """Run one low-effort invocation without exporting prompt or response content."""

    config = ObservabilityConfig(
        observers=(ObserverBinding(MetadataObserver(), PayloadMode.METADATA_ONLY),)
    )
    async with CodexRuntime(observability=config) as runtime:
        model = await runtime.brain(level="low")
        await model.ainvoke("Say hello without exposing this prompt to observers.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
