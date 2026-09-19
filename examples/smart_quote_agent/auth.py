"""Host authentication, masked credential input, and role permission policies."""

from __future__ import annotations

import getpass
import sqlite3
from collections.abc import Callable

from models import AuthenticatedUser

from proteo_runtime.tools import ToolPermissionPolicy

PUBLIC_PERMISSIONS: frozenset[str] = frozenset(
    {
        "catalog.read",
        "quote.calculate",
    }
)

STAFF_PERMISSIONS: frozenset[str] = frozenset(
    {
        "catalog.read",
        "quote.calculate",
        "customer.read",
        "quote.create",
        "quote.read",
    }
)


def authenticate_user_credentials(
    conn: sqlite3.Connection,
    username: str,
    password: str,
) -> AuthenticatedUser | None:
    """Validate credentials against SQLite and return sanitized user identity.

    Crucially, the password argument is discarded immediately and never stored
    on the returned object or logged.

    Args:
        conn: Open SQLite database connection.
        username: Username to authenticate.
        password: Plaintext password to verify.

    Returns:
        AuthenticatedUser if valid, otherwise None.
    """
    clean_username = username.strip()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, username, password, role, display_name, customer_id
        FROM users
        WHERE LOWER(username) = LOWER(?);
        """,
        (clean_username,),
    ).fetchone()

    if row is None:
        return None

    # Compare password and delete local variable immediately
    is_valid = bool(row["password"] == password)
    del password

    if not is_valid:
        return None

    return AuthenticatedUser(
        user_id=int(row["id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        role=row["role"],
        customer_id=int(row["customer_id"]) if row["customer_id"] is not None else None,
    )


def authenticate_user_interactive(
    conn: sqlite3.Connection,
    *,
    input_func: Callable[[str], str] = input,
    getpass_func: Callable[[str], str] = getpass.getpass,
    language: str = "en",
) -> AuthenticatedUser | None:
    """Prompt the user for credentials in the terminal with masked password input.

    Uses getpass to prevent echoing password characters to the terminal.

    Args:
        conn: Open SQLite database connection.
        input_func: Callable for username input (defaults to builtin input).
        getpass_func: Callable for masked password input (defaults to getpass.getpass).
        language: Stable interaction language (`es` or `en`).

    Returns:
        AuthenticatedUser on success, or None on failure.
    """
    is_spanish = language == "es"
    username_prompt = "Usuario: " if is_spanish else "Username: "
    password_prompt = "Contraseña: " if is_spanish else "Password: "
    username = input_func(username_prompt)
    password = getpass_func(password_prompt)
    user = authenticate_user_credentials(conn, username, password)
    del password
    return user


def get_permission_policy_for_user(user: AuthenticatedUser | None) -> ToolPermissionPolicy:
    """Construct the authoritative ToolPermissionPolicy matching the user's role.

    Anonymous and client users receive read/calculate catalog permissions only.
    Staff users receive full operational and quote mutation permissions.

    Args:
        user: Authenticated user, or None if anonymous.

    Returns:
        ToolPermissionPolicy for the active interaction.
    """
    if user is not None and user.role == "staff":
        return ToolPermissionPolicy(STAFF_PERMISSIONS)
    return ToolPermissionPolicy(PUBLIC_PERMISSIONS)
