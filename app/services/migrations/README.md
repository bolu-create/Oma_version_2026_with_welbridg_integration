# Database migrations

This project has no migration framework (Alembic etc.) — the schema in `db.py` is
applied by hand. These files add the two tables the outreach onboarding feature
needs, without touching anything that already exists.

| Table | Purpose |
|-------|---------|
| `oma_outreach_approved_contacts` | Whitelist of pre-approved phone numbers → auto-enrolled with a role at sign-up. |
| `oma_outreach_join_requests` | The "vouch" flow: a prospective field_expert/admin is confirmed by an existing admin. Also stores the conversational state. |

## How to run

From the project root, with your virtualenv active:

```bash
# 1) (optional but recommended) look before you leap — read-only, changes nothing
python migrations/inspect_db.py

# 2) apply the migration
python migrations/run_migration.py migrations/001_add_outreach_onboarding_tables.up.sql

# 3) confirm
python migrations/inspect_db.py
```

To roll back (drops the two tables — destroys their data):

```bash
python migrations/run_migration.py migrations/001_add_outreach_onboarding_tables.down.sql
```

## Notes

- The forward SQL uses `CREATE TABLE IF NOT EXISTS`, so it is **safe to re-run**.
- The DDL was generated directly from the SQLAlchemy models (MySQL dialect), so
  it matches the ORM exactly. The `role` enums are identical to the existing
  `oma_outreach_prog_users.role`, so there is no enum conflict.
- Both new tables foreign-key to `oma_user_registration(id)` (`ON DELETE SET NULL`).
  `inspect_db.py` checks that target exists before you migrate.
- Equivalent shortcut (does the same thing via SQLAlchemy instead of raw SQL):
  `python -c "from functions_outreach import create_outreach_tables; create_outreach_tables()"`.
  The raw-SQL migration is preferred because it's explicit and reviewable.

## Seeding the first admin

The vouch flow needs at least one existing **admin** to bootstrap. After migrating,
whitelist your first admin (their WhatsApp number, international digits, no `+`):

```python
from db import Session
from functions_outreach import add_approved_contact
s = Session()
add_approved_contact(s, "2348166936127", "admin", name="First Admin")
s.close()
```

When that person registers over WhatsApp, they're auto-enrolled as an admin and
can then vouch for field_experts joining from the field.
