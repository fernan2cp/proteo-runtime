"""Internal canonical session descriptor codec."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass

from .errors import SessionMismatchError
from .types import is_secret_key


@dataclass(frozen=True, slots=True)
class SessionDescriptor:
    """Decoded version-one session identity descriptor."""

    provider: str
    provider_session_id: str
    identity_fingerprint: str
    configuration_fingerprint: str
    profile: str
    level: str
    context_policy: str
    security_policy: str


class SessionCodec:
    """Encode and decode non-secret resumable session descriptors."""

    prefix = "prt1."
    _keys = frozenset(
        {
            "version",
            "provider",
            "provider_session_id",
            "identity_fingerprint",
            "configuration_fingerprint",
            "profile",
            "level",
            "context_policy",
            "security_policy",
        }
    )

    @classmethod
    def encode(
        cls,
        *,
        provider: str,
        provider_session_id: str,
        identity_fingerprint: str,
        configuration_fingerprint: str,
        profile: str,
        level: str,
        context_policy: str,
        security_policy: str,
    ) -> str:
        """Return canonical JSON encoded with unpadded base64url."""

        values = {
            "configuration_fingerprint": configuration_fingerprint,
            "context_policy": context_policy,
            "identity_fingerprint": identity_fingerprint,
            "level": level,
            "profile": profile,
            "provider": provider,
            "provider_session_id": provider_session_id,
            "security_policy": security_policy,
            "version": 1,
        }
        if any(
            not isinstance(value, str) or not value
            for key, value in values.items()
            if key != "version"
        ):
            raise SessionMismatchError("Session descriptor values must be non-empty strings")
        payload = json.dumps(
            values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        return cls.prefix + token

    @classmethod
    def decode(cls, descriptor: str) -> SessionDescriptor:
        """Decode and validate a descriptor, redacting malformed details."""

        if not isinstance(descriptor, str) or not descriptor.startswith(cls.prefix):
            raise SessionMismatchError("Unsupported session descriptor prefix")
        encoded = descriptor[len(cls.prefix) :]
        if not encoded:
            raise SessionMismatchError("Empty session descriptor")
        try:
            padded = encoded + "=" * (-len(encoded) % 4)
            raw = base64.b64decode(padded, altchars=b"-_", validate=True)
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
            raise SessionMismatchError("Malformed session descriptor") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != cls._keys
            or payload.get("version") != 1
        ):
            raise SessionMismatchError("Unsupported session descriptor schema")
        if any(is_secret_key(str(key)) for key in payload):
            raise SessionMismatchError("Secret-shaped session fields are not permitted")
        values = {key: payload[key] for key in cls._keys if key != "version"}
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise SessionMismatchError("Invalid session descriptor field types")
        return SessionDescriptor(**values)
