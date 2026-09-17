"""Provider-neutral runtime protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .capabilities import RuntimeCapabilities
from .model import InvocationConfig, RuntimeModel
from .model_info import ModelInfo
from .observability import ObservabilityStatus
from .session import RuntimeSession
from .task import RuntimeTask

if TYPE_CHECKING:
    from proteo_runtime.tools import ToolExecutor, ToolRegistry


@runtime_checkable
class Runtime(Protocol):
    """Async-first lifecycle and model/session factory contract."""

    async def start(self) -> None:
        """Start the runtime without initializing unrelated providers."""

    async def close(self) -> None:
        """Close the runtime and release local resources."""

    async def capabilities(self) -> RuntimeCapabilities:
        """Return runtime capabilities."""

    async def models(self) -> list[ModelInfo]:
        """List available models."""

    def model(self, *, profile: str, level: str = "medium") -> RuntimeModel[Any]:
        """Create a model view for a profile and logical level."""

    async def task(
        self,
        profile: str = "controlled_agent",
        *,
        level: str = "medium",
        instructions: str | None = None,
        config: InvocationConfig | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeTask[Any]:
        """Create a task-scoped ephemeral controlled agent.

        Args:
            profile: Name of the execution profile (defaults to 'controlled_agent').
            level: Logical reasoning effort level ('low', 'medium', 'high', 'ultra').
            instructions: Optional initial task instructions frozen for the task lifetime.
            config: Optional default invocation configuration for turns in this task.
            registry: Optional host-tool registry (mandatory for controlled tool profiles).
            executor: Optional host-tool executor for dispatching tool calls.

        Returns:
            An active RuntimeTask instance bound to a fresh provider task context.

        Raises:
            CapabilityError: If profile has incompatible lifecycle/context policy or tool bindings are invalid.
            ConfigurationError: If configuration is invalid.
        """

    def get_task(self, task_id: str) -> RuntimeTask[Any]:
        """Look up an active in-memory task by its opaque task identifier.

        Args:
            task_id: The unique task identifier string.

        Returns:
            The active RuntimeTask instance.

        Raises:
            SessionNotFoundError: If the task does not exist or has already been closed.
        """

    async def session(
        self,
        profile: str = "session",
        *,
        level: str = "medium",
        config: Any | None = None,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeSession[Any]:
        """Create a resumable session."""

    async def resume_session(
        self,
        session_id: str,
        *,
        registry: ToolRegistry | None = None,
        executor: ToolExecutor | None = None,
    ) -> RuntimeSession[Any]:
        """Resume a previously created session."""

    async def migrate_session(
        self, session_id: str, *, profile: str, level: str = "medium", security_policy: str
    ) -> RuntimeSession[Any]:
        """Migrate a session to an explicitly requested configuration."""

    def observability_status(self) -> ObservabilityStatus:
        """Return the aggregate health of configured observers."""
