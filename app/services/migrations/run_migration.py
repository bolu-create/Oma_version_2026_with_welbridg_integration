"""
Apply (or roll back) a raw-SQL migration against the live database, using the
same engine/credentials the app already uses (db.get_engine_for_mysql_db).

Usage (from the project root, with your venv active):

    # apply the forward migration
    python migrations/run_migration.py migrations/001_add_outreach_onboarding_tables.up.sql

    # roll it back
    python migrations/run_migration.py migrations/001_add_outreach_onboarding_tables.down.sql

The forward migration is idempotent (CREATE TABLE IF NOT EXISTS), so it is safe
to run more than once. Run migrations/inspect_db.py first if you want to check
the current state without changing anything.
"""

import sys
import os

# make sure we can import db.py when run as `python migrations/run_migration.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from db import engine


def _split_statements(sql_text):
    """Strip -- comment lines and split into individual statements on ';'."""
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def run(path):
    with open(path, "r", encoding="utf-8") as fh:
        sql_text = fh.read()

    statements = _split_statements(sql_text)
    if not statements:
        print(f"Nothing to run in {path}")
        return

    print(f"Applying {len(statements)} statement(s) from {path} ...")
    with engine.begin() as conn:                 # begin() => commits on success, rolls back on error
        for i, stmt in enumerate(statements, 1):
            preview = " ".join(stmt.split())[:70]
            print(f"  [{i}/{len(statements)}] {preview} ...")
            conn.execute(text(stmt))
    print("Done. ✅")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1])
