"""SQLite database operations, schema creation, query helpers, and quote persistence."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "demo.sqlite3"

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY,
    username     TEXT NOT NULL UNIQUE,
    password     TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('staff', 'client')),
    display_name TEXT NOT NULL,
    customer_id  INTEGER NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY,
    sku              TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL,
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS quotes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id           INTEGER NOT NULL,
    created_by_user_id    INTEGER NOT NULL,
    created_at            TEXT NOT NULL,
    currency              TEXT NOT NULL DEFAULT 'USD',
    subtotal_cents        INTEGER NOT NULL CHECK (subtotal_cents >= 0),
    discount_percent      INTEGER NOT NULL DEFAULT 0
                              CHECK (discount_percent BETWEEN 0 AND 30),
    discount_amount_cents INTEGER NOT NULL DEFAULT 0
                              CHECK (discount_amount_cents >= 0),
    total_cents           INTEGER NOT NULL CHECK (total_cents >= 0),
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS quote_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id         INTEGER NOT NULL,
    product_id       INTEGER NOT NULL,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    subtotal_cents   INTEGER NOT NULL CHECK (subtotal_cents >= 0),
    FOREIGN KEY (quote_id) REFERENCES quotes(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
);
"""


def get_db_path() -> Path:
    """Return the default SQLite database path.

    Returns:
        Path to the demo.sqlite3 file.
    """
    return DEFAULT_DB_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a new SQLite connection with foreign keys and row factory enabled.

    Args:
        db_path: Optional path to the database file; defaults to DEFAULT_DB_PATH.

    Returns:
        Configured sqlite3.Connection.
    """
    target = db_path if db_path is not None else get_db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: Path | None = None, *, reset: bool = False) -> None:
    """Initialize database tables, optionally dropping existing schema first.

    Args:
        db_path: Target database path.
        reset: If True, drop existing tables before creating schema.
    """
    target = db_path if db_path is not None else get_db_path()
    if reset and target.exists():
        target.unlink()

    conn = get_connection(target)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def seed_database(db_path: Path | None = None) -> None:
    """Seed default customers, users, and products into the database.

    Args:
        db_path: Target database path.
    """
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        # Seed customers
        customers = [
            (1, "client1", "Acme Corp."),
            (2, "client2", "Globex LLC"),
            (3, "client3", "Initech"),
            (4, "client4", "Northwind Traders"),
        ]
        cur.executemany(
            "INSERT OR IGNORE INTO customers (id, code, name) VALUES (?, ?, ?);",
            customers,
        )

        # Seed users (password is trivial 1234 for demo purposes)
        users = [
            (1, "staff", "1234", "staff", "Demo Staff", None),
            (2, "client1", "1234", "client", "Client 1", 1),
            (3, "client2", "1234", "client", "Client 2", 2),
            (4, "client3", "1234", "client", "Client 3", 3),
            (5, "client4", "1234", "client", "Client 4", 4),
        ]
        cur.executemany(
            """
            INSERT OR IGNORE INTO users
            (id, username, password, role, display_name, customer_id)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            users,
        )

        # Seed products
        products = [
            (1, "NB-PRO", "Notebook Pro", "High performance notebook computer", 120000, 1),
            (2, "NB-AIR", "Notebook Air", "Ultra-thin lightweight notebook", 90000, 1),
            (3, "MS-WL", "Wireless Mouse", "Ergonomic precision wireless mouse", 4000, 1),
            (4, "KB-MECH", "Mechanical Keyboard", "Tactile mechanical switch keyboard", 8500, 1),
            (5, "MON-27", '27" Monitor', "27-inch 4K UHD external monitor", 32000, 1),
            (6, "DOCK-USBC", "USB-C Dock", "USB-C multi-display docking station", 15000, 1),
        ]
        cur.executemany(
            """
            INSERT OR IGNORE INTO products
            (id, sku, name, description, unit_price_cents, active)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            products,
        )
        conn.commit()
    finally:
        conn.close()


def cents_to_decimal(cents: int) -> Decimal:
    """Convert integer cents to Decimal dollar amount.

    Args:
        cents: Amount in integer cents.

    Returns:
        Decimal dollars value.
    """
    return Decimal(cents) / Decimal(100)


def calculate_discount_amount(subtotal_cents: int, discount_percent: int) -> int:
    """Compute the discount amount in integer cents using ROUND_HALF_UP.

    Args:
        subtotal_cents: Subtotal amount in integer cents.
        discount_percent: Discount percentage between 0 and 30.

    Returns:
        Discount amount in integer cents.

    Raises:
        ValueError: If discount_percent is outside 0..30.
    """
    if not (0 <= discount_percent <= 30):
        raise ValueError("discount_percent must be between 0 and 30")
    subtotal = Decimal(subtotal_cents)
    pct = Decimal(discount_percent)
    amount = (subtotal * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(amount)


def format_currency(cents: int) -> str:
    """Format integer cents as USD string.

    Args:
        cents: Amount in integer cents.

    Returns:
        Formatted string like '$1,200.00'.
    """
    dollars = cents_to_decimal(cents)
    return f"${dollars:,.2f}"


def _escape_like(text: str) -> str:
    """Escape SQL LIKE wildcard characters for safe substring queries.

    Args:
        text: Raw user query string.

    Returns:
        Escaped string with backslashes preceding % and _.
    """
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def find_customer_by_query(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    """Find a customer by exact ID, code, or name, or unique partial match.

    Resolution order:
    1. Exact ID match (if query is numeric);
    2. Exact code match (case-insensitive);
    3. Exact name match (case-insensitive);
    4. Unique partial name match (case-insensitive, wildcards escaped).
    If multiple partial matches are found, an ambiguous result dictionary is returned.

    Args:
        conn: Open SQLite connection.
        query: Customer identifier, code, or name to search.

    Returns:
        Dictionary with customer fields, ambiguity dictionary, or None if not found.
    """
    clean = query.strip()
    if not clean:
        return None
    cur = conn.cursor()

    # 1. Exact ID
    if clean.isdigit():
        row = cur.execute(
            "SELECT id, code, name FROM customers WHERE id = ?;",
            (int(clean),),
        ).fetchone()
        if row is not None:
            return dict(row)

    # 2. Exact code
    row = cur.execute(
        "SELECT id, code, name FROM customers WHERE LOWER(code) = LOWER(?);",
        (clean,),
    ).fetchone()
    if row is not None:
        return dict(row)

    # 3. Exact name
    row = cur.execute(
        "SELECT id, code, name FROM customers WHERE LOWER(name) = LOWER(?);",
        (clean,),
    ).fetchone()
    if row is not None:
        return dict(row)

    # 4. Partial name match
    escaped = _escape_like(clean)
    rows = cur.execute(
        "SELECT id, code, name FROM customers WHERE LOWER(name) LIKE LOWER(?) ESCAPE '\\';",
        (f"%{escaped}%",),
    ).fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    if len(rows) > 1:
        candidates = [f"{r['name']} ({r['code']})" for r in rows]
        return {
            "ambiguous": True,
            "candidates": candidates,
            "message": f"Multiple customers matched '{clean}': {', '.join(candidates)}. Please specify exact name or code.",
        }

    return None


def list_active_products(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """List all currently active products.

    Args:
        conn: Open SQLite connection.

    Returns:
        List of product dictionaries ordered by SKU.
    """
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, sku, name, description, unit_price_cents, active
        FROM products
        WHERE active = 1
        ORDER BY sku;
        """
    ).fetchall()
    return [dict(r) for r in rows]


def find_product_by_query(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    """Find a product by exact SKU, ID, or name, or unique partial match.

    Resolution order:
    1. Exact ID match (if query is numeric);
    2. Exact SKU match (case-insensitive);
    3. Exact name match (case-insensitive);
    4. Unique partial name match (case-insensitive, wildcards escaped).
    If multiple partial matches are found, an ambiguous result dictionary is returned.

    Args:
        conn: Open SQLite connection.
        query: Product SKU, ID, or partial name.

    Returns:
        Dictionary with product fields, ambiguity dictionary, or None if not found.
    """
    clean = query.strip()
    if not clean:
        return None
    cur = conn.cursor()

    # 1. Exact ID
    if clean.isdigit():
        row = cur.execute(
            """
            SELECT id, sku, name, description, unit_price_cents, active
            FROM products
            WHERE id = ? AND active = 1;
            """,
            (int(clean),),
        ).fetchone()
        if row is not None:
            return dict(row)

    # 2. Exact SKU
    row = cur.execute(
        """
        SELECT id, sku, name, description, unit_price_cents, active
        FROM products
        WHERE LOWER(sku) = LOWER(?) AND active = 1;
        """,
        (clean,),
    ).fetchone()
    if row is not None:
        return dict(row)

    # 3. Exact name
    row = cur.execute(
        """
        SELECT id, sku, name, description, unit_price_cents, active
        FROM products
        WHERE LOWER(name) = LOWER(?) AND active = 1;
        """,
        (clean,),
    ).fetchone()
    if row is not None:
        return dict(row)

    # 4. Partial name match
    escaped = _escape_like(clean)
    rows = cur.execute(
        """
        SELECT id, sku, name, description, unit_price_cents, active
        FROM products
        WHERE LOWER(name) LIKE LOWER(?) ESCAPE '\\' AND active = 1;
        """,
        (f"%{escaped}%",),
    ).fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    if len(rows) > 1:
        candidates = [f"{r['name']} ({r['sku']})" for r in rows]
        return {
            "ambiguous": True,
            "candidates": candidates,
            "message": f"Multiple products matched '{clean}': {', '.join(candidates)}. Please specify exact SKU or name.",
        }

    return None


def get_quote_by_id(conn: sqlite3.Connection, quote_id: int) -> dict[str, Any] | None:
    """Fetch complete quote details including all line items.

    Args:
        conn: Open SQLite connection.
        quote_id: Primary key of the quote.

    Returns:
        Dictionary with quote header and 'lines' list, or None if not found.
    """
    if quote_id <= 0:
        return None
    cur = conn.cursor()
    quote_row = cur.execute(
        """
        SELECT q.id, q.customer_id, c.name AS customer_name, c.code AS customer_code,
               q.created_by_user_id, u.display_name AS creator_name,
               q.created_at, q.currency, q.subtotal_cents,
               q.discount_percent, q.discount_amount_cents, q.total_cents
        FROM quotes q
        JOIN customers c ON q.customer_id = c.id
        JOIN users u ON q.created_by_user_id = u.id
        WHERE q.id = ?;
        """,
        (quote_id,),
    ).fetchone()
    if quote_row is None:
        return None

    quote_dict = dict(quote_row)
    lines_rows = cur.execute(
        """
        SELECT ql.id, ql.product_id, p.sku, p.name,
               ql.quantity, ql.unit_price_cents, ql.subtotal_cents
        FROM quote_lines ql
        JOIN products p ON ql.product_id = p.id
        WHERE ql.quote_id = ?
        ORDER BY ql.id;
        """,
        (quote_id,),
    ).fetchall()
    quote_dict["lines"] = [dict(r) for r in lines_rows]
    return quote_dict


def list_recent_quotes(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    """List recent quotes ordered by creation timestamp descending.

    Args:
        conn: Open SQLite connection.
        limit: Maximum number of records to return (bounded between 1 and 50).

    Returns:
        List of quote summary dictionaries.
    """
    bounded_limit = max(1, min(50, limit))
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT q.id, q.customer_id, c.name AS customer_name,
               q.created_at, q.total_cents, q.currency, u.display_name AS creator_name
        FROM quotes q
        JOIN customers c ON q.customer_id = c.id
        JOIN users u ON q.created_by_user_id = u.id
        ORDER BY q.created_at DESC, q.id DESC
        LIMIT ?;
        """,
        (bounded_limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def persist_quote_transactional(
    conn: sqlite3.Connection,
    *,
    customer_id: int,
    created_by_user_id: int,
    lines: list[tuple[int, int]],  # list of (product_id, quantity)
    discount_percent: int,
) -> int:
    """Atomically create a quote and all quote lines in a single SQLite transaction.

    This function executes under an immediate SQLite transaction, re-reading
    authoritative product prices from the database, enforcing all quote invariants,
    computing line and total amounts, and committing atomically.

    Args:
        conn: Open SQLite connection.
        customer_id: Target customer ID.
        created_by_user_id: Authenticated staff user ID creating the quote.
        lines: List of (product_id, quantity) tuples.
        discount_percent: Whole discount percentage in range 0..30.

    Returns:
        Inserted quote primary key (ID).

    Raises:
        ValueError: If validation fails (e.g. invalid customer, inactive product, bad discount).
    """
    if not (0 <= discount_percent <= 30):
        raise ValueError("discount_percent must be between 0 and 30")
    if not lines:
        raise ValueError("At least one quote line is required")

    try:
        conn.execute("BEGIN IMMEDIATE TRANSACTION;")
        cur = conn.cursor()

        # Validate customer exists
        cust = cur.execute("SELECT id FROM customers WHERE id = ?;", (customer_id,)).fetchone()
        if cust is None:
            raise ValueError(f"Customer {customer_id} does not exist")

        # Validate creator exists and is staff
        user = cur.execute(
            "SELECT id, role FROM users WHERE id = ?;",
            (created_by_user_id,),
        ).fetchone()
        if user is None or user["role"] != "staff":
            raise ValueError(f"User {created_by_user_id} is not an authorized staff user")

        # Re-read authoritative product prices and validate lines
        computed_lines: list[tuple[int, int, int, int]] = []
        subtotal_cents = 0

        for product_id, quantity in lines:
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero")
            prod = cur.execute(
                "SELECT id, unit_price_cents, active FROM products WHERE id = ?;",
                (product_id,),
            ).fetchone()
            if prod is None or prod["active"] != 1:
                raise ValueError(f"Product {product_id} not found or inactive")

            unit_price = int(prod["unit_price_cents"])
            line_subtotal = unit_price * quantity
            subtotal_cents += line_subtotal
            computed_lines.append((product_id, quantity, unit_price, line_subtotal))

        discount_amount = calculate_discount_amount(subtotal_cents, discount_percent)
        total_cents = subtotal_cents - discount_amount
        created_at = datetime.now(UTC).isoformat()

        cur.execute(
            """
            INSERT INTO quotes
            (customer_id, created_by_user_id, created_at, currency,
             subtotal_cents, discount_percent, discount_amount_cents, total_cents)
            VALUES (?, ?, ?, 'USD', ?, ?, ?, ?);
            """,
            (
                customer_id,
                created_by_user_id,
                created_at,
                subtotal_cents,
                discount_percent,
                discount_amount,
                total_cents,
            ),
        )
        quote_id = cur.lastrowid
        if quote_id is None:
            raise RuntimeError("Failed to obtain inserted quote ID")

        line_records = [
            (quote_id, prod_id, qty, unit_price, line_sub)
            for prod_id, qty, unit_price, line_sub in computed_lines
        ]
        cur.executemany(
            """
            INSERT INTO quote_lines
            (quote_id, product_id, quantity, unit_price_cents, subtotal_cents)
            VALUES (?, ?, ?, ?, ?);
            """,
            line_records,
        )
        conn.commit()
        return int(quote_id)
    except Exception:
        conn.rollback()
        raise
