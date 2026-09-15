"""Capability-gated configuration for Codex-native OpenTelemetry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import urlsplit

from proteo_runtime.core.types import is_secret_key


@dataclass(frozen=True, slots=True)
class CodexNativeOtelConfig:
    """Explicit, non-secret configuration forwarded to the Codex process."""

    enabled: bool = False
    exporter: str = "otlp"
    endpoint: str | None = None
    protocol: str = "http/protobuf"
    service_name: str = "proteo-runtime"
    environment: str | None = None
    tls_ca_path: str | None = None
    tls_certificate_path: str | None = None
    tls_key_path: str | None = None
    log_user_prompt: bool = False
    resource_attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate provider-neutral safe fields and force prompt privacy."""

        if self.exporter not in {"otlp", "console", "none"}:
            raise ValueError("Unsupported Codex-native OTel exporter")
        if self.protocol not in {"grpc", "http/protobuf"}:
            raise ValueError("Unsupported Codex-native OTel protocol")
        if self.endpoint:
            parsed = urlsplit(self.endpoint)
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Codex-native OTel endpoint must not contain credentials")
        attributes: dict[str, str] = {}
        for key, value in self.resource_attributes.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise TypeError("Codex-native OTel resource attributes must be string pairs")
            if is_secret_key(key):
                raise ValueError("Codex-native OTel resource attributes must not contain secrets")
            attributes[key] = value
        object.__setattr__(self, "log_user_prompt", False)
        object.__setattr__(self, "resource_attributes", MappingProxyType(attributes))

    def overrides(self) -> tuple[str, ...]:
        """Return Codex CLI config overrides without secret headers."""

        if not self.enabled:
            return ()
        values: list[tuple[str, str]] = [
            ("otel.enabled", "true"),
            ("otel.exporter", self.exporter),
            ("otel.protocol", self.protocol),
            ("otel.service_name", self.service_name),
            ("otel.log_user_prompt", "false"),
        ]
        optional = {
            "otel.endpoint": self.endpoint,
            "otel.environment": self.environment,
            "otel.tls_ca_path": self.tls_ca_path,
            "otel.tls_certificate_path": self.tls_certificate_path,
            "otel.tls_key_path": self.tls_key_path,
        }
        values.extend((key, value) for key, value in optional.items() if value is not None)
        values.extend(
            (f"otel.resource.{key}", value) for key, value in self.resource_attributes.items()
        )
        return tuple(f"{key}={value}" for key, value in values)


@dataclass(frozen=True, slots=True)
class CodexNativeOtelCapabilities:
    """Reported support for the pinned SDK's native telemetry surface."""

    configured: bool
    supported: bool
    correlation_propagation: bool = False
    reason: str | None = None


def native_otel_capabilities(config: CodexNativeOtelConfig | None) -> CodexNativeOtelCapabilities:
    """Return capability state without importing the optional SDK."""

    if config is None or not config.enabled:
        return CodexNativeOtelCapabilities(False, False, reason="disabled")
    try:
        from openai_codex import CodexConfig

        fields = getattr(CodexConfig, "__dataclass_fields__", {})
        supported = "config_overrides" in fields
    except ImportError:
        supported = False
    return CodexNativeOtelCapabilities(
        configured=True,
        supported=supported,
        correlation_propagation=False,
        reason=None if supported else "sdk does not expose config overrides",
    )


__all__ = [
    "CodexNativeOtelCapabilities",
    "CodexNativeOtelConfig",
    "native_otel_capabilities",
]
