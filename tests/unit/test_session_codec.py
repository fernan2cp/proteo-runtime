"""Session descriptor codec tests."""

import base64
import json

import pytest

from proteo_runtime.core.errors import SessionMismatchError
from proteo_runtime.core.session_codec import SessionCodec


def _encoded() -> str:
    """Return a deterministic valid descriptor."""

    return SessionCodec.encode(
        provider="fake",
        provider_session_id="s-1",
        identity_fingerprint="id-1",
        configuration_fingerprint="cfg-1",
        profile="session",
        level="medium",
        context_policy="runtime",
        security_policy="isolated",
    )


def test_codec_round_trip_is_deterministic_and_unpadded() -> None:
    """Canonical encoding round-trips and uses the required prefix."""

    first = _encoded()
    assert first == _encoded() and first.startswith("prt1.") and not first.endswith("=")
    assert SessionCodec.decode(first).provider_session_id == "s-1"


def test_codec_rejects_malformed_versions_extra_and_secret_fields() -> None:
    """Malformed descriptors and credential-shaped payload keys are rejected."""

    for value in ("", "bad", "prt1.!", "prt2.abc"):
        with pytest.raises(SessionMismatchError):
            SessionCodec.decode(value)
    payload = {"version": 1, "token": "secret"}
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(SessionMismatchError):
        SessionCodec.decode("prt1." + raw)


def test_codec_supports_optional_migration_nonce_and_rejects_invalid_values() -> None:
    """Migration descriptors may carry a nonce while old v1 descriptors remain valid."""

    descriptor = SessionCodec.encode(
        provider="fake",
        provider_session_id="s-1",
        identity_fingerprint="id-1",
        configuration_fingerprint="cfg-1",
        profile="session",
        level="medium",
        context_policy="runtime",
        security_policy="isolated",
        descriptor_nonce="migration-1",
    )
    assert SessionCodec.decode(descriptor).descriptor_nonce == "migration-1"
    with pytest.raises(SessionMismatchError):
        SessionCodec.encode(
            provider="fake",
            provider_session_id="s-1",
            identity_fingerprint="id-1",
            configuration_fingerprint="cfg-1",
            profile="session",
            level="medium",
            context_policy="runtime",
            security_policy="isolated",
            descriptor_nonce="",
        )
