"""Public API surface contract tests."""

import proteo_runtime


def test_root_exports_are_exactly_the_documented_contracts() -> None:
    """The root package exposes only documented provider-neutral names."""

    expected = {
        "__version__",
        "AgentRuntimeError",
        "AuthenticationError",
        "CancellationError",
        "CapabilityError",
        "ConfigurationError",
        "ContextLimitError",
        "ContextPolicy",
        "ContextPolicyError",
        "DiagnosticSeverity",
        "ExecutionProfile",
        "HostToolsMode",
        "InterruptedError",
        "InvocationConfig",
        "LifecycleMode",
        "LogicalLevel",
        "ModelInfo",
        "ObservabilityError",
        "ProfileSpec",
        "RetryExhaustedError",
        "Runtime",
        "RuntimeCapabilities",
        "RuntimeDiagnostic",
        "RuntimeEvent",
        "RuntimeEventKind",
        "RuntimeIdentity",
        "RuntimeInput",
        "RuntimeMessage",
        "RuntimeModel",
        "RuntimeResult",
        "RuntimeSession",
        "RuntimeTimeoutError",
        "RuntimeUnavailableError",
        "RuntimeUsage",
        "SecurityPolicyError",
        "SecurityPolicy",
        "SessionBusyError",
        "SessionMismatchError",
        "SessionNotFoundError",
        "StructuredOutputError",
        "TextContent",
        "ToolDeniedError",
        "ToolExecutionError",
    }
    assert set(proteo_runtime.__all__) == expected
    assert not hasattr(proteo_runtime, "SessionCodec")
    assert not any(name.startswith("Fake") for name in proteo_runtime.__all__)


def test_root_exports_resolve_to_provider_neutral_modules() -> None:
    """Every exported contract resolves from the package or core namespaces."""

    for name in proteo_runtime.__all__:
        assert getattr(proteo_runtime, name) is not None
        module = getattr(proteo_runtime, name).__module__ if name != "__version__" else ""
        assert not any(
            token in module for token in ("openai", "langgraph", "langsmith", "opentelemetry")
        )
