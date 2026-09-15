"""Safe mappings between Codex SDK values and Proteo contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast

from proteo_runtime.core.errors import AuthenticationError
from proteo_runtime.core.input import RuntimeInput


def enum_value(value: object) -> str | None:
    """Return a stable string for an enum or ordinary value."""

    if value is None:
        return None
    return str(getattr(value, "value", value))


def fingerprint(value: Mapping[str, object]) -> str:
    """Hash canonical metadata without retaining credentials."""

    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def account_value(response: object) -> object | None:
    """Extract the account union from a Codex account response or test double."""

    nested = getattr(response, "account", None)
    if nested is not None:
        root = getattr(nested, "root", None)
        return cast(object, root if root is not None else nested)
    root = getattr(response, "root", None)
    return cast(object, root if root is not None else response)


def identity_metadata(response: object) -> tuple[str, Mapping[str, Any]]:
    """Normalize ChatGPT account metadata into a secret-free fingerprint."""

    account = account_value(response)
    if enum_value(getattr(account, "type", None)) != "chatgpt":
        raise AuthenticationError("Codex requires ChatGPT-managed authentication")
    email = getattr(account, "email", None)
    plan = enum_value(getattr(account, "plan_type", None)) or "unknown"
    normalized_email = str(email).strip().lower() if email else ""
    precision = "exact" if normalized_email else "degraded"
    material = {
        "provider": "codex",
        "auth_mode": "chatgpt",
        "email": normalized_email,
        "plan_type": plan,
    }
    return fingerprint(material), MappingProxyType(
        {"auth_mode": "chatgpt", "plan_type": plan, "identity_precision": precision}
    )


def serialize_input(value: str | RuntimeInput) -> tuple[str, str | None]:
    """Serialize input deterministically and extract system instructions."""

    runtime_input = RuntimeInput.from_value(value)
    system = [message.text for message in runtime_input.messages if message.role == "system"]
    transcript = [
        f"[{message.role}]\n{message.text}"
        for message in runtime_input.messages
        if message.role != "system"
    ]
    prompt = "\n\n".join(transcript).strip()
    if not prompt:
        raise ValueError("Runtime input must contain a non-system message")
    return prompt, "\n\n".join(system).strip() or None


def safe_raw(value: object) -> Mapping[str, str]:
    """Return a small immutable diagnostic mapping with no SDK objects."""

    if isinstance(value, Mapping):
        selected = {
            str(key): str(item)
            for key, item in value.items()
            if str(key).lower() in {"status", "type", "id", "error"}
        }
    else:
        selected = {"type": type(value).__name__}
    return MappingProxyType(selected)
