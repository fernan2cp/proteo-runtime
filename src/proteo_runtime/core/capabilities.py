"""Runtime capability declarations."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    """Immutable feature support advertised by a runtime."""

    structured_output: bool = False
    ephemeral_sessions: bool = True
    ephemeral_tasks: bool = False
    persistent_sessions: bool = False
    streaming: bool = True
    interruption: bool = False
    host_tools: bool = False
    native_tools: bool = False
    sandbox: bool = True
    usage_reporting: bool = True
