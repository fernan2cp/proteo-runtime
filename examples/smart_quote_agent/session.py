"""Session controller and lifecycle management for identity-bound RuntimeTask instances."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from models import AuthenticatedUser
from tools import create_tool_executor, get_agent_tool_registry

from proteo_runtime.core.events import RuntimeEvent
from proteo_runtime.core.task import RuntimeTask, TaskState
from proteo_runtime.tools import ApprovalHandler

AGENT_INSTRUCTIONS = (
    "You are ONLY the Smart Quote Agent for this application.\n"
    "Your conversational scope is strictly limited to product exploration, "
    "authoritative pricing inquiries, non-persisted quote calculations, and quote reviews (staff only).\n"
    "Rules:\n"
    "- Do not answer general-purpose requests outside this scope.\n"
    "- Do not claim capabilities simply because the underlying model could normally perform them.\n"
    "- You do NOT have arbitrary internet browsing, filesystem access, code execution/editing, "
    "image generation, document analysis, external connected applications, shell access, or "
    "unrestricted network tools.\n"
    "- Always use host-managed tools for business facts. Never invent products, prices, "
    "customers, or persisted quotes.\n"
    "- Do NOT narrate tool execution, intermediate steps, or progress (e.g., never say "
    "'Voy a consultar...', 'Let me check...', or 'Voy a revisar el catálogo...'). "
    "NEVER send intermediate thinking or announcements before invoking tools. "
    "Query tools directly and return only the final synthesized answer to the user.\n"
    "- You maintain conversational context across turns, but remember only the read-only "
    "conversational turns routed to this runtime task. "
    "The host workflow, not you, owns quote-creation state and persistence.\n"
    "- When a host message says a quote workflow remains pending, do not claim that you changed "
    "its customer, products, quantities, or persistence state.\n"
    "- Reply in the user's language.\n"
    "- Treat tool permission denial as authoritative.\n"
    "- Never claim that quote persistence occurred unless a host tool reports success.\n"
    "- If an out-of-scope request reaches this node unexpectedly, do not answer the request. "
    "Return only: 'That request is outside the scope of this agent. I can help you consult "
    "products, prices, or calculate a preliminary quote preview.'"
)


def format_agent_instructions(
    user: AuthenticatedUser | None,
    base_instructions: str = AGENT_INSTRUCTIONS,
) -> str:
    """Format task instructions binding current identity role.

    Args:
        user: Authenticated user identity, or None if anonymous.
        base_instructions: Base system instructions string.

    Returns:
        Formatted instructions string frozen for the task lifetime.
    """
    role_label = user.role if user is not None else "anonymous"
    return f"{base_instructions}\nCurrent role: {role_label}\n"


class AgentSessionManager:
    """Manages the identity-bound lifecycle of RuntimeTask for the controlled agent."""

    def __init__(
        self,
        runtime: Any,
        conn: sqlite3.Connection,
        *,
        instructions: str | None = None,
        approval_handler: ApprovalHandler | None = None,
        event_sink: Callable[[RuntimeEvent], Awaitable[Any]] | None = None,
        host_event_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        """Initialize the session manager.

        Args:
            runtime: Active Runtime instance (CodexRuntime or FakeRuntime).
            conn: SQLite database connection.
            instructions: Optional custom base instructions.
            approval_handler: Optional Phase 5 approval handler.
            event_sink: Optional async event sink for observability.
            host_event_sink: Optional metadata-only sink for host diagnostics.
        """
        self._runtime = runtime
        self._conn = conn
        self._base_instructions = instructions or AGENT_INSTRUCTIONS
        self._approval_handler = approval_handler
        self._event_sink = event_sink
        self._host_event_sink = host_event_sink
        self._active_task: RuntimeTask[Any] | None = None
        self._current_user: AuthenticatedUser | None = None
        self._closed = False
        self._lock = asyncio.Lock()

    @property
    def active_task(self) -> RuntimeTask[Any] | None:
        """Return the currently active RuntimeTask, or None if no task exists."""
        return self._active_task

    @property
    def current_user(self) -> AuthenticatedUser | None:
        """Return the identity bound to the currently active task."""
        return self._current_user

    def get_active_task(self) -> RuntimeTask[Any] | None:
        """Callable returning the active task for graph invocation.

        Returns:
            The active RuntimeTask instance or None.
        """
        return self._active_task

    async def get_or_create_task(self, user: AuthenticatedUser | None) -> RuntimeTask[Any]:
        """Get the active task if identity matches, or create a new one.

        Args:
            user: Authenticated user identity or None for anonymous.

        Returns:
            Active RuntimeTask bound to the requested identity.
        """
        async with self._lock:
            if self._active_task is not None:
                current_state = getattr(self._active_task, "state", None)
                is_terminal = current_state in (
                    TaskState.CLOSING,
                    TaskState.CLOSED,
                    "closing",
                    "closed",
                ) or getattr(current_state, "is_terminal", False)
                if self._current_user == user and not is_terminal:
                    return self._active_task
                await self._close_active_task_locked()
            return await self._create_task_locked(user)

    async def switch_identity(self, user: AuthenticatedUser | None) -> RuntimeTask[Any]:
        """Close any active task and create a fresh task for the new identity.

        Args:
            user: New authenticated user identity or None for anonymous.

        Returns:
            Newly created RuntimeTask bound to the new identity.
        """
        async with self._lock:
            await self._close_active_task_locked()
            return await self._create_task_locked(user)

    async def _close_active_task_locked(self) -> None:
        """Close the currently active task under lock."""
        if self._active_task is not None:
            task = self._active_task
            self._active_task = None
            close_failed = False
            try:
                await task.close()
            except Exception:
                close_failed = True
            diagnostics = getattr(task, "diagnostics", ())
            recorded_cleanup_failure = False
            for diagnostic in diagnostics:
                code = getattr(diagnostic, "code", None)
                if not isinstance(code, str) or not code.startswith("task.cleanup."):
                    continue
                recorded_cleanup_failure = True
                self._record_cleanup_diagnostic(task, code)
            if close_failed and not recorded_cleanup_failure:
                self._record_cleanup_diagnostic(task, "task.cleanup.close_failed")

    def _record_cleanup_diagnostic(self, task: RuntimeTask[Any], code: str) -> None:
        """Persist one sanitized task cleanup diagnostic when a sink is configured.

        Args:
            task: Runtime task that emitted the cleanup diagnostic.
            code: Stable diagnostic code only; exception and provider details are excluded.
        """
        if self._host_event_sink is None:
            return
        try:
            self._host_event_sink(
                {
                    "task_id": task.id,
                    "event_kind": code,
                    "diagnostic_code": code,
                    "result_code": code,
                }
            )
        except Exception:
            # Cleanup telemetry must never prevent identity or task lifecycle changes.
            return

    async def _create_task_locked(self, user: AuthenticatedUser | None) -> RuntimeTask[Any]:
        """Create and register a new task for the given user under lock.

        Args:
            user: Authenticated user identity or None for anonymous.

        Returns:
            Active RuntimeTask handle.
        """
        self._current_user = user
        registry = get_agent_tool_registry(self._conn, user)
        executor = create_tool_executor(
            registry,
            user,
            approval_handler=self._approval_handler,
            event_sink=self._event_sink,
        )
        task_instructions = format_agent_instructions(user, self._base_instructions)
        task = await self._runtime.task(
            profile="controlled_agent",
            level="low",
            instructions=task_instructions,
            registry=registry,
            executor=executor,
        )
        self._active_task = task
        return cast(RuntimeTask[Any], task)

    async def close(self) -> None:
        """Close the active task and shut down the session manager."""
        async with self._lock:
            await self._close_active_task_locked()
            self._closed = True
