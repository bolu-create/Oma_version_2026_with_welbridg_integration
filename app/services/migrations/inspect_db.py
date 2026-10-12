"""
READ-ONLY inspection of the live database. Changes nothing.

Run this before and/or after the migration to confirm your setup is healthy and
that migration 001 has no conflicts:

    python migrations/inspect_db.py

It reports:
  * every table currently in the database,
  * whether the FK target table (oma_user_registration) exists,
  * whether the two new tables already exist, and if so their columns
    (so you can spot any drift from the models in db.py),
  * a readiness verdict for migration 001.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect
from db import engine

NEW_TABLES = ["oma_outreach_approved_contacts", "oma_outreach_join_requests"]
FK_TARGET = "oma_user_registration"

# expected columns (name -> type substring) straight from the models in db.py,
# used only to flag obvious drift if a table already exists.
EXPECTED = {
    "oma_outreach_approved_contacts": [
        "id", "phone_number", "name", "role", "added_by", "is_enrolled", "created_at",
    ],
    "oma_outreach_join_requests": [
        "id", "requester_user_id", "requester_wa_id", "requester_name", "requested_role",
        "stage", "vouching_admin_name", "vouching_admin_phone", "vouching_admin_user_id",
        "created_at", "resolved_at",
    ],
}


def main():
    insp = inspect(engine)
    tables = sorted(insp.get_table_names())

    print("=" * 70)
    print(f"Connected. {len(tables)} table(s) found:")
    for t in tables:
        print(f"   - {t}")
    print("=" * 70)

    # FK target present?
    if FK_TARGET in tables:
        print(f"[OK]   FK target '{FK_TARGET}' exists — foreign keys can be created.")
    else:
        print(f"[STOP] FK target '{FK_TARGET}' is MISSING — migration 001 will fail. "
              f"Create the user-registration table first.")

    # new tables
    for t in NEW_TABLES:
        if t not in tables:
            print(f"[NEW]  '{t}' does not exist yet — migration will create it.")
            continue
        cols = {c["name"] for c in insp.get_columns(t)}
        expected = set(EXPECTED[t])
        missing = expected - cols
        extra = cols - expected
        print(f"[HAVE] '{t}' already exists with columns: {sorted(cols)}")
        if missing:
            print(f"         !! missing expected columns: {sorted(missing)}")
        if extra:
            print(f"         !! unexpected extra columns: {sorted(extra)}")
        if not missing and not extra:
            print(f"         columns match the model — nothing to do.")

    print("=" * 70)
    need = [t for t in NEW_TABLES if t not in tables]
    if FK_TARGET not in tables:
        print("VERDICT: NOT READY — create oma_user_registration first.")
    elif need:
        print(f"VERDICT: READY — run migration 001 to create: {need}")
    else:
        print("VERDICT: Both tables already present. Migration 001 is a no-op.")
    print("=" * 70)


if __name__ == "__main__":
    main()
