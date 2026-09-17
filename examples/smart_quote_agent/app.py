"""Interactive CLI entrypoint and REPL loop for Smart Quote Agent."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Ensure demo directory is in sys.path when executed directly
_DEMO_DIR = str(Path(__file__).resolve().parent)
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

from auth import authenticate_user_interactive  # noqa: E402
from database import get_connection, get_db_path, init_database, seed_database  # noqa: E402
from graph import create_demo_graph  # noqa: E402
from hitl import ConsoleApprovalHandler, prompt_discount_interactive  # noqa: E402
from models import AuthenticatedUser, DemoState  # noqa: E402
from observability import ObservabilityManager  # noqa: E402

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


async def _run_repl_loop(
    app_graph: Any,
    *,
    input_func: Callable[[str], str],
    interactive: bool,
) -> None:
    """Execute the unified turn-by-turn interactive REPL loop.

    Args:
        app_graph: Compiled LangGraph state graph.
        input_func: Callable for reading user input.
        interactive: Whether to print prompts and outputs.
    """
    current_user: AuthenticatedUser | None = None

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

        initial_state: DemoState = {
            "input": user_input,
            "authenticated_user": current_user,
        }

        try:
            result = await app_graph.ainvoke(initial_state)
            current_user = result.get("authenticated_user")
            output_text = result.get("output", "")
            if output_text and interactive:
                print(f"\n{output_text}\n")
        except Exception as err:
            print(f"\n[ERROR] Request failed: {err}\n")


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

    def auth_interactive(c: sqlite3.Connection) -> AuthenticatedUser | None:
        return authenticate_user_interactive(c, input_func=input_func, getpass_func=getpass_func)

    approval_handler = ConsoleApprovalHandler(input_func=input_func)

    def discount_prompter(cents: int) -> int:
        return prompt_discount_interactive(cents, input_func=input_func)

    if interactive:
        mode_label = "anonymous (offline)" if offline else "anonymous"
        print("=" * 60)
        print("Proteo Runtime - Smart Quote Agent")
        print("=" * 60)
        print(f"\nMode: {mode_label}")
        print("Type 'login' to sign in.")
        print("Type 'logout' to sign out.")
        print("Type 'exit' to quit.\n")

    obs_mgr = ObservabilityManager()

    try:
        if offline:
            app_graph = create_demo_graph(
                conn,
                structured_model=None,
                controlled_agent_model=None,
                approval_handler=approval_handler,
                discount_prompter=discount_prompter,
                auth_interactive=auth_interactive,
                event_sink=obs_mgr.bus.emit,
            )
            await _run_repl_loop(app_graph, input_func=input_func, interactive=interactive)
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
                controlled_agent_model = runtime.model(profile="controlled_agent", level="low")

                app_graph = create_demo_graph(
                    conn,
                    structured_model=structured_model,
                    controlled_agent_model=controlled_agent_model,
                    approval_handler=approval_handler,
                    discount_prompter=discount_prompter,
                    auth_interactive=auth_interactive,
                    event_sink=obs_mgr.bus.emit,
                )
                await _run_repl_loop(app_graph, input_func=input_func, interactive=interactive)
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
