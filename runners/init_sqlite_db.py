"""
Initialize the Smart PLC Assistant SQLite database schema.

Usage:
    python runners/init_sqlite_db.py
    python runners/init_sqlite_db.py --drop-existing
    python runners/init_sqlite_db.py --echo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DATABASE_PATH
from core.database import health_check, init_sqlite_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize SQLite schema for Smart PLC Assistant")
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop existing tables before creating schema",
    )
    parser.add_argument(
        "--echo",
        action="store_true",
        help="Enable SQL logging",
    )
    args = parser.parse_args()

    print("Initializing SQLite database schema...")
    print(f"Database file: {Path(DATABASE_PATH).resolve()}")

    tables = init_sqlite_database(drop_existing=args.drop_existing, echo=args.echo)
    ok = health_check()

    print()
    print("Schema initialized.")
    print(f"Tables ({len(tables)}):")
    for name in tables:
        print(f"- {name}")

    print()
    print(f"Health check: {'OK' if ok else 'FAILED'}")


if __name__ == "__main__":
    main()
