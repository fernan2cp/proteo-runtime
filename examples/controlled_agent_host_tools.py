"""Minimal controlled-agent host-tool example using only neutral contracts."""

from __future__ import annotations

import asyncio

from proteo_runtime.tools import (
    ToolExecutor,
    ToolPermissionPolicy,
    ToolRegistry,
    ToolRequest,
    runtime_tool,
)


@runtime_tool(
    name="lookup_status",
    description="Read a local status value.",
    permission="status.read",
)
async def lookup_status(service: str) -> str:
    """Return a deterministic host-owned status value."""

    return f"{service}: ready"


async def main() -> None:
    """Register and execute the example tool with exact permission matching."""

    registry = ToolRegistry()
    registry.register(lookup_status)
    executor = ToolExecutor(
        registry,
        permission_policy=ToolPermissionPolicy(frozenset({"status.read"})),
    )
    result = await executor.execute(
        ToolRequest("example-invocation", "example-call", "lookup_status", {"service": "api"})
    )
    print(result.as_provider_value())


if __name__ == "__main__":
    asyncio.run(main())
