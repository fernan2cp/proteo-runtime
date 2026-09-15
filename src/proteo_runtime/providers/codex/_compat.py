"""Private compatibility shims for the pinned Codex SDK."""

from __future__ import annotations

from typing import Any, Protocol

from proteo_runtime.core.errors import CapabilityError


class _Client(Protocol):
    """Minimal generic-request boundary used by the deletion shim."""

    async def request(self, method: str, params: dict[str, Any], *, response_model: Any) -> Any:
        """Send one typed request."""


class _SDK(Protocol):
    """SDK surface needed by the deletion shim."""

    _client: _Client


async def delete_thread(sdk: _SDK, thread_id: str) -> None:
    """Delete one thread through the isolated typed request boundary."""

    try:
        from openai_codex.generated.v2_all import ThreadDeleteParams, ThreadDeleteResponse
    except ImportError as exc:
        raise CapabilityError("Codex thread deletion is unavailable") from exc
    params = ThreadDeleteParams(thread_id=thread_id)
    payload = params.model_dump(by_alias=True, exclude_none=True)
    await sdk._client.request("thread/delete", payload, response_model=ThreadDeleteResponse)
