"""Database initialization and seeding script for Smart Quote Agent."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure examples/smart_quote_agent is on sys.path when run directly
_DEMO_DIR = Path(__file__).resolve().parent
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

from database import get_db_path, init_database, seed_database  # noqa: E402


def main() -> None:
    """Initialize or reset the Smart Quote Agent demo database."""
    parser = argparse.ArgumentParser(
        description="Initialize or reset the Smart Quote Agent SQLite database.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop existing data and recreate a freshly seeded database.",
    )
    args = parser.parse_args()

    db_path = get_db_path()
    already_existed = db_path.exists()

    if already_existed and not args.reset:
        print(f"Database already exists at {db_path}.")
        print("Run with --reset to wipe and re-initialize with default demo data.")
        return

    init_database(db_path, reset=args.reset)
    seed_database(db_path)

    print("Smart Quote Agent demo initialized.\n")
    print(f"Database:\n{db_path}\n")
    print("Users:")
    print("staff   / 1234")
    print("client1 / 1234")
    print("client2 / 1234")
    print("client3 / 1234")
    print("client4 / 1234")


if __name__ == "__main__":
    main()
