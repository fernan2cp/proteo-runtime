"""Interactive CLI entrypoint and REPL loop for Smart Quote Agent."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import sqlite3
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Ensure demo directory is in sys.path when executed directly
_DEMO_DIR = str(Path(__file__).resolve().parent)
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from auth import authenticate_user_interactive  # noqa: E402
from database import get_connection, get_db_path, init_database, seed_database  # noqa: E402
from graph import create_demo_graph, resolve_language  # noqa: E402
from hitl import ConsoleApprovalHandler, prompt_discount_interactive  # noqa: E402
from models import AuthenticatedUser, DemoState  # noqa: E402
from observability import ObservabilityManager  # noqa: E402
from session import AgentSessionManager  # noqa: E402

from proteo_runtime.providers.codex import CodexRuntime  # noqa: E402


def get_cli_prompt(user: AuthenticatedUser | None) -> str:
    """Format the interactive CLI prompt string based on current authentication mode.

    Args:
        user: Currently authenticated user, or None if anonymous.

    Returns:
        Formatted prompt string.
    """
    if user is None:
        return "> "
    return f"[{user.username}] > "


def _print_startup_banner(*, offline: bool) -> None:
    """Explain the demo, access modes, credentials, and basic commands."""
    mode_label = "Anónimo (sin conexión)" if offline else "Anónimo"
    print("=" * 60)
    print("Proteo Runtime - Smart Quote Agent")
    print("=" * 60)
    print(f"\nModo actual: {mode_label}")
    if offline:
        print("Ejecución offline: el agente no se conecta a Codex.\n")
    print("Este demo permite consultar el catálogo activo y preparar cotizaciones.")
    print("Los precios se calculan desde el catálogo local de demostración.")
    print("\nModos de acceso:")
    print("- Anónimo: consulta productos y calcula vistas preliminares; no guarda cotizaciones.")
    print("- Cliente: lo mismo, asociado a su empresa; no crea cotizaciones guardadas.")
    print("- Staff: puede listar clientes, ver cotizaciones y crear con aprobación.")
    print("\nPara iniciar sesión, escribí 'login' y completá usuario y contraseña.")
    print("La contraseña se ingresa oculta. Credenciales de este demo (todas usan 1234):")
    print("- Staff: staff")
    print("- Clientes: client1 (Acme Corp.), client2 (Globex LLC),")
    print("  client3 (Initech), client4 (Northwind Traders)")
    print("Son cuentas de demostración; no las uses fuera de este ejemplo.")
    print("\nEscribí 'logout' para volver al modo anónimo y 'exit' para salir.\n")


async def _run_repl_loop(
    app_graph: Any,
    *,
    input_func: Callable[[str], str],
    interactive: bool,
    host_error_sink: Callable[..., None] | None = None,
    task_id_provider: Callable[[], str | None] | None = None,
) -> None:
    """Execute the unified turn-by-turn interactive REPL loop.

    Args:
        app_graph: Compiled LangGraph state graph.
        input_func: Callable for reading user input.
        interactive: Whether to print prompts and outputs.
        host_error_sink: Optional best-effort sink for sanitized host errors.
        task_id_provider: Optional provider for the active runtime task ID.
    """
    current_user: AuthenticatedUser | None = None
    state: DemoState = {
        "input": "",
        "authenticated_user": None,
        "pending_action": None,
        "pending_quote_request": None,
        "quote_workflow": None,
        "quote_request": None,
        "quote_draft": None,
        "quote_patch": None,
        "language": "en",
    }

    while True:
        prompt_str = get_cli_prompt(current_user)
        try:
            user_input = input_func(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            if interactive:
                print("\nExiting.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            if interactive:
                print("Goodbye.")
            break

        state["input"] = user_input
        state["authenticated_user"] = current_user
        interaction_id = uuid.uuid4().hex
        state["interaction_id"] = interaction_id

        try:
            result = await app_graph.ainvoke(state)
            current_user = result.get("authenticated_user")
            state["authenticated_user"] = current_user
            state["pending_action"] = result.get("pending_action")
            state["pending_quote_request"] = result.get("pending_quote_request")
            state["quote_workflow"] = result.get("quote_workflow")
            state["quote_request"] = result.get("quote_request")
            state["quote_draft"] = result.get("quote_draft")
            state["quote_patch"] = result.get("quote_patch")
            state["language"] = result.get("language", state.get("language", "en"))

            if current_user is None:
                state["pending_action"] = None
                state["pending_quote_request"] = None
                state["quote_workflow"] = None
                state["quote_request"] = None
                state["quote_draft"] = None
                state["quote_patch"] = None

            output_text = result.get("output", "")
            if output_text and interactive:
                print(f"\n{output_text}\n")
        except Exception as error:
            if host_error_sink is not None:
                stage = getattr(error, "_smart_quote_stage", "graph.invoke")
                if not isinstance(stage, str):
                    stage = "graph.invoke"
                try:
                    task_id = task_id_provider() if task_id_provider is not None else None
                except Exception:
                    task_id = None
                workflow = state.get("quote_workflow")
                workflow_id = getattr(workflow, "workflow_id", None)
                with contextlib.suppress(Exception):
                    host_error_sink(
                        error,
                        stage=stage,
                        interaction_id=interaction_id,
                        task_id=task_id,
                        workflow_id=workflow_id if isinstance(workflow_id, str) else None,
                    )
                # Diagnostics are best effort and must not block the REPL.
            lang = resolve_language(user_input, state.get("language"))
            state["language"] = lang
            message = (
                "No se pudo procesar la solicitud. Inténtalo de nuevo."
                if lang == "es"
                else "The request could not be processed. Please try again."
            )
            print(f"\n[ERROR] {message}\n")


async def run_cli_loop(
    *,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass.getpass,
    runtime_override: Any = None,
    interactive: bool = True,
    offline: bool = False,
) -> None:
    """Execute the interactive CLI application.

    Args:
        input_func: Callable for user input.
        getpass_func: Callable for masked password input.
        runtime_override: Optional runtime double for testing.
        interactive: Whether to print startup banner and prompts.
        offline: When True, run without connecting to live Codex runtime.
    """
    db_path = get_db_path()
    if not db_path.exists():
        if interactive:
            print("Database not found. Initializing with default seed data...")
        init_database(db_path, reset=True)
        seed_database(db_path)

    conn = get_connection(db_path)

    def auth_interactive(
        c: sqlite3.Connection, *, language: str = "en"
    ) -> AuthenticatedUser | None:
        return authenticate_user_interactive(
            c,
            input_func=input_func,
            getpass_func=getpass_func,
            language=language,
        )

    approval_handler = ConsoleApprovalHandler(input_func=input_func)

    def discount_prompter(cents: int, *, language: str = "en") -> int:
        return prompt_discount_interactive(cents, input_func=input_func, language=language)

    if interactive:
        _print_startup_banner(offline=offline)

    obs_mgr = ObservabilityManager()

    try:
        if offline:
            app_graph = create_demo_graph(
                conn,
                structured_model=None,
                context_agent=None,
                session_manager=None,
                approval_handler=approval_handler,
                discount_prompter=discount_prompter,
                auth_interactive=auth_interactive,
                event_sink=obs_mgr.bus.emit,
                host_event_sink=obs_mgr.record_host_event,
                host_error_sink=obs_mgr.record_host_error,
            )
            await _run_repl_loop(
                app_graph,
                input_func=input_func,
                interactive=interactive,
                host_error_sink=obs_mgr.record_host_error,
            )
        else:
            runtime_cm = (
                CodexRuntime(
                    observability=obs_mgr.runtime_config,
                    experimental_dynamic_tools=True,
                )
                if runtime_override is None
                else runtime_override
            )
            async with runtime_cm as runtime:
                structured_model = runtime.model(profile="structured", level="low")
                session_mgr = AgentSessionManager(
                    runtime,
                    conn,
                    approval_handler=approval_handler,
                    event_sink=obs_mgr.bus.emit,
                    host_event_sink=obs_mgr.record_host_event,
                )
                await session_mgr.get_or_create_task(None)

                app_graph = create_demo_graph(
                    conn,
                    structured_model=structured_model,
                    context_agent=session_mgr.get_active_task,
                    session_manager=session_mgr,
                    approval_handler=approval_handler,
                    discount_prompter=discount_prompter,
                    auth_interactive=auth_interactive,
                    event_sink=obs_mgr.bus.emit,
                    host_event_sink=obs_mgr.record_host_event,
                    host_error_sink=obs_mgr.record_host_error,
                )
                try:
                    await _run_repl_loop(
                        app_graph,
                        input_func=input_func,
                        interactive=interactive,
                        host_error_sink=obs_mgr.record_host_error,
                        task_id_provider=lambda: (
                            session_mgr.active_task.id
                            if session_mgr.active_task is not None
                            else None
                        ),
                    )
                finally:
                    await session_mgr.close()
    finally:
        await obs_mgr.close()
        conn.close()


def main() -> None:
    """Run the Smart Quote Agent CLI application entrypoint."""
    parser = argparse.ArgumentParser(
        description="Proteo Runtime - Smart Quote Agent CLI Demo",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run explicitly in offline mode without connecting to live Codex.",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_cli_loop(offline=args.offline))
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    main()
