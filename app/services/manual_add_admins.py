"""
Manually add someone to the outreach programme — usually the FIRST admin.

Why this exists
---------------
Outreach approvals are self-sustaining once one admin exists: that admin can
promote everyone else by talking to Oma. But the very first admin has nobody to
approve them, so they have to be created out of band. This is that door.

It is also the fallback for the team when someone is stuck — a broadcast that
never landed, a rejected application that should have been approved, a field
agent who needs elevating today.

What it does
------------
1. Looks the person up by phone number.
2. If they are not registered, registers them from scratch — the same row
   register_user() would create during Oma's normal sign-up, so they end up
   indistinguishable from someone who signed up over WhatsApp.
3. Marks the account approved (otherwise they'd be outreach staff who still
   can't get past the approval gate in generate_response).
4. Enrols them in the outreach programme with the role you asked for.
5. Optionally messages them to say so.

Everything is idempotent — running it twice on the same person changes nothing
and reports what was already true.

Running it
----------
The database host is `mysql.railway.internal`, which only resolves INSIDE
Railway. So either:

  * run it in the Railway container (a one-off command on the service), or
  * point the DB_* env vars at Railway's public TCP proxy and run it locally.

    python manual_add_admins.py 2348166936127 "Micheal Odunsi" mich@example.com
    python manual_add_admins.py 2348012345678 "Musa Ibrahim" musa@example.com --role field_expert
    python manual_add_admins.py 2348012345678 --no-notify

If you cannot run Python against the database at all, the equivalent SQL is in
the module docstring of add_admin() below.
"""

import os
import sys

# Same bootstrap the migrations use: these modules import each other by bare name
# ("from db import *"), which only resolves when this directory is on sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import Session, OmaUserRegistration, OmaOutreachProgramUsers, OutreachRole
from datetime import datetime

from functions_1 import register_user
from functions_outreach import (
    add_outreach_program_user,
    _normalize_phone,
    send_whatsapp_message,
)


def find_user(session, phone_number):
    """The registered account for this phone, or None. Phone is normalised the
    same way the webhook normalises wa_id, so '+234...', '234...' and
    'whatsapp:+234...' all find the same person."""
    phone = _normalize_phone(phone_number)
    return (
        session.query(OmaUserRegistration)
        .filter(OmaUserRegistration.phone_number == phone)
        .first()
    )


def describe_user(session, phone_number):
    """Read-only summary of where someone stands. Safe to call any time."""
    user = find_user(session, phone_number)
    if user is None:
        return {"registered": False, "phone_number": _normalize_phone(phone_number)}

    roles = (
        session.query(OmaOutreachProgramUsers)
        .filter(OmaOutreachProgramUsers.user_id == user.id)
        .all()
    )
    return {
        "registered": True,
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "phone_number": user.phone_number,
        "is_approved": bool(user.is_approved),
        "outreach_roles": [
            {"role": r.role.value, "is_active": bool(r.is_active)} for r in roles
        ],
    }


def add_admin(phone_number, username=None, email=None, role="admin", notify=True,
              session=None):
    """Create-if-missing, then enrol into the outreach programme.

    Args:
        phone_number: with or without '+' / country-code punctuation.
        username:     required only if the person is not already registered.
        email:        required only if the person is not already registered.
        role:         "admin" (default) or "field_expert".
        notify:       WhatsApp them that they've been added. Only works if they
                      have messaged the business in the last 24h — Meta rejects
                      business-initiated messages outside that window.
        session:      pass one to join an existing transaction; otherwise a
                      session is opened and closed here.

    Returns a dict describing what changed.

    Equivalent SQL, if you'd rather do it by hand (run one at a time):
        UPDATE oma_user_registration
           SET is_approved = 1, approved_at = NOW()
         WHERE phone_number = '<digits>';

        INSERT INTO oma_outreach_prog_users (user_id, role, is_active, date_added)
        SELECT id, 'admin', 1, NOW() FROM oma_user_registration
         WHERE phone_number = '<digits>';
    """
    owns_session = session is None
    session = session or Session()
    changes = []

    try:
        phone = _normalize_phone(phone_number)
        try:
            role_enum = role if isinstance(role, OutreachRole) else OutreachRole(str(role).strip().lower())
        except ValueError:
            valid = ", ".join(r.value for r in OutreachRole)
            return {"status": "error", "message": f"'{role}' is not a valid role. Valid: {valid}"}

        user = find_user(session, phone)

        # 1. Register from scratch if they've never met Oma.
        if user is None:
            if not username or not email:
                return {
                    "status": "needs_details",
                    "message": (f"+{phone} isn't registered yet, so I need a username and an "
                                f"email to create the account. Pass both as arguments."),
                }
            register_user(session, username, email, phone)
            user = find_user(session, phone)
            if user is None:
                return {"status": "error",
                        "message": "Registration did not persist — check the database connection."}
            changes.append(f"registered {username} <{email}>")
        else:
            changes.append(f"found existing account: {user.username} (id={user.id})")

        # 2. Approve the account. Outreach staff still pass through the approval
        #    gate in generate_response, so skipping this leaves them locked out.
        if not user.is_approved:
            user.is_approved = True
            user.approved_at = datetime.utcnow()
            session.commit()
            changes.append("marked account approved")

        # 3. Enrol with the role (reactivates rather than duplicating).
        existing = (
            session.query(OmaOutreachProgramUsers)
            .filter(
                OmaOutreachProgramUsers.user_id == user.id,
                OmaOutreachProgramUsers.role == role_enum,
            )
            .first()
        )
        already_active = bool(existing and existing.is_active)

        prog = add_outreach_program_user(session, user.id, role_enum)
        if prog is None:
            return {"status": "error", "message": "Could not create the outreach role row."}

        if already_active:
            changes.append(f"already an active {role_enum.value} — nothing to change")
        else:
            changes.append(f"enrolled as {role_enum.value}")

        # 4. Tell them, unless asked not to.
        notified = False
        if notify and not already_active:
            role_label = role_enum.value.replace("_", " ")
            notified = send_whatsapp_message(
                user.phone_number,
                (f"Good news {user.username}! 🎉 You've been added to the Welbridg rural "
                 f"outreach programme as a {role_label}. Say hello to Oma and I'll walk "
                 f"you through what you can do."))
            changes.append("notified them" if notified else
                           "could NOT notify them (likely Meta's 24-hour window)")

        return {
            "status": "ok",
            "user_id": user.id,
            "username": user.username,
            "phone_number": user.phone_number,
            "role": role_enum.value,
            "notified": notified,
            "changes": changes,
        }

    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"{type(e).__name__}: {e}", "changes": changes}
    finally:
        if owns_session:
            session.close()


def target_database():
    """Which database this process will actually talk to.

    Worth printing before anything else: db.py calls load_dotenv() at import, so
    running from app/services picks up app/services/.env — which may still hold
    an old host from a previous deployment. Connecting somewhere you didn't
    expect looks identical to the database being down.
    """
    return {
        "host": os.getenv("SQL_HOST_SERVER"),
        "port": os.getenv("DB_PORT", "3306"),
        "database": os.getenv("DB_DATABASE"),
        "user": os.getenv("MY_USERNAME"),
    }


def _connection_help(target, exc):
    return f"""
Could not reach the database.

  host     : {target['host']}
  port     : {target['port']}
  database : {target['database']}
  user     : {target['user']}

  {type(exc).__name__}: {str(exc)[:200]}

Check the host above is the one you meant. Two things bite here:

  * 'mysql.railway.internal' only resolves INSIDE Railway. From a laptop it
    cannot work at all — run this as a one-off command on the Railway service,
    or point the vars below at Railway's public TCP proxy.

  * A stale app/services/.env overrides what you think you set. db.py calls
    load_dotenv() at import, so that file wins when you run from this folder.

To run locally against Railway, set these first (values from the MySQL
service's Variables tab, using the PUBLIC proxy host and port):

  SQL_HOST_SERVER   MY_USERNAME   PASSWORD   DB_DATABASE   DB_PORT

If you can't connect at all, the equivalent SQL is in add_admin()'s docstring.
"""


def _main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    phone = argv[0]
    positional = [a for a in argv[1:] if not a.startswith("--")]
    username = positional[0] if len(positional) > 0 else None
    email = positional[1] if len(positional) > 1 else None

    role = "admin"
    for a in argv[1:]:
        if a.startswith("--role"):
            role = a.split("=", 1)[1] if "=" in a else argv[argv.index(a) + 1]
    notify = "--no-notify" not in argv

    target = target_database()
    print(f"\nDatabase: {target['user']}@{target['host']}:{target['port']}/{target['database']}")

    # Probe the connection before doing anything, so an unreachable database
    # reports itself clearly instead of surfacing as a SQLAlchemy traceback.
    try:
        before = describe_user(Session(), phone)
    except Exception as e:
        print(_connection_help(target, e))
        return 2

    print(f"Before:   {before}\n")

    result = add_admin(phone, username=username, email=email, role=role, notify=notify)

    print(f"Result: {result.get('status')}")
    if result.get("message"):
        print(f"  {result['message']}")
    for c in result.get("changes", []):
        print(f"  - {c}")

    try:
        print(f"\nAfter:    {describe_user(Session(), phone)}\n")
    except Exception:
        pass
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
