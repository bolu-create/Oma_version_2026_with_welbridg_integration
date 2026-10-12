"""
Web chat endpoints: the Welbridg site talks to Oma here.

Same agent, same database, same memory as WhatsApp. The differences are all at
the edge:

  * Identity comes from the user's Supabase login, verified with Supabase on
    every request. The email is read from the verified token, never from the
    request body, so nobody can open someone else's conversation by typing
    their email.
  * Web users are already registered with Welbridg, so they skip Oma's
    registration/approval chat. Their Oma record is found by email (which is
    how a WhatsApp user's history carries over), or created already approved.
  * Replies take 10-30s, longer than a browser request should hang. POST
    /web/chat queues the message and returns a job id; the page polls
    GET /web/chat/<job_id>. Jobs run on the SAME single-worker agent_pool as
    WhatsApp, so a user's messages stay in order whichever channel they use.

Endpoints:
    POST /web/chat            {text, image?, timezone?}  -> 202 {job_id}
    GET  /web/chat/<job_id>   -> {status: pending|done|error, reply?, error?}
    GET  /web/history         -> {messages: [...]}
    GET  /web/documents       -> {documents: [...]}

Config (env): SUPABASE_URL, SUPABASE_ANON_KEY, WEB_ALLOWED_ORIGINS
(comma-separated, defaults to http://localhost:5173).
"""

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import traceback
from datetime import datetime
from functools import wraps

import requests
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func

# Importing through the same path whatsapp_utils uses keeps a single copy of
# each service module (and so one engine, one Session factory). The services
# package also puts its folder on sys.path for the flat imports below.
from app.services.fresh_version_with_new_db import generate_response, Session
import channel
import documents
import s3_storage
from db import OmaChatHistory, OmaUserDocument, OmaUserRegistration
from functions_1 import approve_user, register_user

from .views import agent_pool

web_blueprint = Blueprint("web", __name__, url_prefix="/web")

# Every web log line is tagged "oma.web" so the web flow can be followed with
#   grep "oma.web"
# Each message gets a job id; QUEUED / START / DONE (or FAILED) lines for that
# id give the queue wait and how long the agent itself took.
log = logging.getLogger("oma.web")


class _QuietPolls(logging.Filter):
    """The page asks "is my reply ready?" every ~1.5s. Those request lines
    drown everything else, so successful polls are dropped from the access log;
    the job's START/DONE lines carry the useful part."""
    def filter(self, record):
        msg = record.getMessage()
        return not ("GET /web/chat/" in msg and '" 200' in msg)


logging.getLogger("werkzeug").addFilter(_QuietPolls())    # local dev server
logging.getLogger("gunicorn.access").addFilter(_QuietPolls())

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY") or ""
ALLOWED_ORIGINS = {
    o.strip().rstrip("/")
    for o in (os.getenv("WEB_ALLOWED_ORIGINS") or "http://localhost:5173").split(",")
    if o.strip()
}

MAX_TEXT_CHARS = 4000
# Matches MAX_IMAGE_BYTES on the WhatsApp side; base64 adds a third.
MAX_IMAGE_B64_CHARS = (3 * 1024 * 1024 * 4) // 3 + 100
IMAGE_DATA_URI = re.compile(r"^data:(image/(?:jpeg|png));base64,[A-Za-z0-9+/=]+$")
TIMEZONE_NAME = re.compile(r"^[A-Za-z0-9_+\-/]{1,64}$")
HISTORY_LIMIT = 60
JOB_TTL_SECONDS = 3600


# ── CORS ──────────────────────────────────────────────────────────────────
# Only these routes are called from the browser, so CORS lives here rather
# than app-wide. Preflight OPTIONS requests are answered by Flask's automatic
# OPTIONS handling and pick up these headers on the way out.

@web_blueprint.after_request
def add_cors_headers(response):
    origin = (request.headers.get("Origin") or "").rstrip("/")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "600"
        response.headers["Vary"] = "Origin"
    return response


# ── Auth ──────────────────────────────────────────────────────────────────

# sha256(token) -> (expires_at, user). The page polls every ~1.5s while Oma is
# thinking; without this every poll would be a round trip to Supabase.
_token_cache = {}
_token_cache_lock = threading.Lock()
TOKEN_CACHE_SECONDS = 60


def _verify_supabase_token(token):
    """Ask Supabase who this token belongs to. Returns a user dict or None."""
    key = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _token_cache_lock:
        hit = _token_cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except requests.RequestException as e:
        log.error(f"auth: Supabase unreachable: {e}")
        return None
    if resp.status_code != 200:
        log.warning(f"auth: Supabase rejected the token (HTTP {resp.status_code})")
        return None

    data = resp.json()
    email = (data.get("email") or "").strip().lower()
    # An unconfirmed email proves nothing about who is behind it, and email is
    # what links a web user to their WhatsApp history.
    if not email or not data.get("email_confirmed_at"):
        log.warning(f"auth: refused {email or 'user without email'} - email not confirmed")
        return None
    log.info(f"auth: verified {email} with Supabase")

    meta = data.get("user_metadata") or {}
    user = {
        "id": data["id"],
        "email": email,
        "name": (meta.get("full_name") or email.split("@")[0]).strip()[:255],
    }
    with _token_cache_lock:
        if len(_token_cache) > 5000:
            for k in [k for k, v in _token_cache.items() if v[0] <= now]:
                del _token_cache[k]
        _token_cache[key] = (now + TOKEN_CACHE_SECONDS, user)
    return user


def web_auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not SUPABASE_URL or not SUPABASE_ANON_KEY:
            logging.error("web auth: SUPABASE_URL / SUPABASE_ANON_KEY not configured")
            return jsonify({"message": "Oma's web chat isn't configured yet."}), 503
        header = request.headers.get("Authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        user = _verify_supabase_token(token) if token else None
        if not user:
            return jsonify({"message": "Please log in again."}), 401
        g.web_user = user
        return view(*args, **kwargs)
    return wrapped


# ── Identity: Welbridg user -> Oma user ──────────────────────────────────

def _web_wa_id(supabase_user_id):
    """Stand-in wa_id for web users with no Oma record yet. phone_number/wa_id
    are VARCHAR(20); "web-" + 12 hex chars is 16. It never collides with a real
    WhatsApp number, so lookups by wa_id can't land on someone else's history.
    It gets replaced once the user verifies their number on WhatsApp."""
    return "web-" + supabase_user_id.replace("-", "")[:12]


def resolve_oma_user(session, web_user):
    """Find (or create) the Oma registration for a verified Welbridg user.

    Matched on email, which is what lets a WhatsApp user see that history on
    the web. Never matched on the phone in their Welbridg profile: that number
    is unverified, and matching on it would let anyone read a stranger's
    WhatsApp conversation by typing their number in.

    Returns (user_id, wa_id, name).
    """
    rows = (session.query(OmaUserRegistration)
            .filter(func.lower(OmaUserRegistration.email) == web_user["email"])
            .all())

    if rows:
        # Several WhatsApp registrations can share an email (it was never
        # unique). Prefer an approved one, then the oldest.
        row = sorted(rows, key=lambda r: (not r.is_approved, r.created_at or datetime.min))[0]
        log.debug(f"identity: {web_user['email']} -> Oma user {row.id} ({row.phone_number})"
                  f"{' (one of %d with this email)' % len(rows) if len(rows) > 1 else ''}")
        if not row.is_approved:
            # Welbridg has already verified this person; no manual approval.
            # Set on this row directly: approve_user() looks up by phone, and
            # phone numbers aren't unique.
            row.is_approved = True
            row.approved_at = datetime.utcnow()
            session.commit()
        return row.id, row.phone_number, row.username

    wa_id = _web_wa_id(web_user["id"])
    existing = session.query(OmaUserRegistration).filter_by(phone_number=wa_id).first()
    if existing:  # email changed in Welbridg since we created it
        existing.email = web_user["email"]
        session.commit()
        return existing.id, existing.phone_number, existing.username

    register_user(session, web_user["name"], web_user["email"], wa_id)
    approve_user(session, wa_id)
    created = session.query(OmaUserRegistration).filter_by(phone_number=wa_id).first()
    log.info(f"identity: created Oma user {created.id} ({wa_id}) for {web_user['email']}")
    return created.id, wa_id, created.username


# ── Jobs ──────────────────────────────────────────────────────────────────
# In memory: the app runs one gunicorn worker (see Procfile), so every request
# and every agent thread sees the same dict. A restart loses pending jobs;
# the page gives up after two minutes and says so.

_jobs = {}
_jobs_lock = threading.Lock()


def _prune_jobs():
    cutoff = time.time() - JOB_TTL_SECONDS
    for job_id in [k for k, v in _jobs.items() if v["created"] < cutoff]:
        del _jobs[job_id]


def _has_pending_job(owner):
    return any(j["owner"] == owner and j["status"] == "pending" for j in _jobs.values())


def _location_text(tz_name):
    """What the agent is told about where the user is, from the browser's zone."""
    if not tz_name or not TIMEZONE_NAME.match(tz_name):
        return None
    try:
        from zoneinfo import ZoneInfo
        offset = datetime.now(ZoneInfo(tz_name)).strftime("%z")
        offset = f"UTC{offset[:3]}:{offset[3:]}"
    except Exception:
        offset = "unknown UTC offset"
    return (f"The user is chatting on the Welbridg website. Their device's time zone is "
            f"{tz_name} ({offset}); use it for any times or reminders.")


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _run_web_job(app_obj, job_id, wa_id, name, message_body, message_type, location):
    """Runs on the agent_pool worker, after any WhatsApp messages ahead of it."""
    with app_obj.app_context():
        token = channel.start(channel.WEB, country=location)
        session = Session()
        started = time.time()
        with _jobs_lock:
            queued_at = _jobs.get(job_id, {}).get("created", started)
        log.info(f"[job {job_id}] START after {started - queued_at:.1f}s in queue "
                 f"(type={message_type}, wa_id={wa_id})")
        try:
            text = generate_response(session, message_body, message_type, wa_id, name)
            if not isinstance(text, str) or not text.strip():
                text = "Sorry, I couldn't come up with an answer to that. Could you try again?"
            reply = {
                "id": f"oma-{job_id}",
                "role": "oma",
                "channel": channel.WEB,
                "text": re.sub(r"【.*?】", "", text).strip(),
                "created_at": _iso(datetime.utcnow()),
                "attachments": channel.attachments(),
            }
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update(status="done", reply=reply)
            log.info(f"[job {job_id}] DONE in {time.time() - started:.1f}s "
                     f"(total {time.time() - queued_at:.1f}s incl. queue) - "
                     f"{len(reply['text'])} chars, {len(reply['attachments'])} attachment(s)")
        except Exception as e:
            log.error(f"[job {job_id}] FAILED after {time.time() - started:.1f}s: {e}\n{traceback.format_exc()}")
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id].update(status="error",
                                         error="Oma ran into a problem answering that. Please try again.")
        finally:
            session.close()
            channel.finish(token)


# ── Routes ────────────────────────────────────────────────────────────────

@web_blueprint.route("/chat", methods=["POST"])
@web_auth_required
def post_chat():
    user = g.web_user
    log.info(f"POST /web/chat from {user['email']}: {request.content_length or 0} bytes")
    if (request.content_length or 0) > MAX_IMAGE_B64_CHARS + MAX_TEXT_CHARS * 4 + 2000:
        log.warning("  rejected: body too large")
        return jsonify({"message": "That message is too large."}), 413

    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    image = body.get("image") or None

    if len(text) > MAX_TEXT_CHARS:
        log.warning(f"  rejected: text too long ({len(text)} chars)")
        return jsonify({"message": f"Please keep messages under {MAX_TEXT_CHARS} characters."}), 400

    mime = None
    if image:
        match = IMAGE_DATA_URI.match(image) if isinstance(image, str) else None
        if not match or len(image) > MAX_IMAGE_B64_CHARS:
            log.warning(f"  rejected: bad image (prefix={str(image)[:30]!r}, {len(str(image))} chars)")
            return jsonify({"message": "Oma can read JPG and PNG photos up to 3 MB."}), 400
        mime = match.group(1)

    if not text and not image:
        log.warning("  rejected: empty message")
        return jsonify({"message": "Type a message or attach a photo."}), 400

    log.info(f"  text={len(text)} chars, image={'%s %d KB' % (mime, len(image) * 3 // 4 // 1024) if image else 'none'}, "
             f"tz={body.get('timezone')}")

    with _jobs_lock:
        if _has_pending_job(user["id"]):
            log.warning("  rejected: a reply is already pending for this user")
            return jsonify({"message": "Oma is still answering your last message."}), 409

    session = Session()
    try:
        _, wa_id, name = resolve_oma_user(session, user)
    except Exception as e:
        session.rollback()
        logging.error(f"web: resolving user failed: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Oma couldn't load your account. Please try again."}), 500
    finally:
        session.close()

    # Same shapes the WhatsApp path builds: plain text, or a content list with
    # the photo (plus caption) and the image mime as message_type, which is
    # what makes generate_response describe the image.
    if image:
        message_body = ([{"type": "text", "text": text}] if text else []) + \
                       [{"type": "image_url", "image_url": {"url": image}}]
        message_type = mime
        documents.remember_photo(wa_id, image)   # so "save that photo" works later
    else:
        message_body = text
        message_type = "text"

    job_id = secrets.token_urlsafe(12)
    with _jobs_lock:
        _prune_jobs()
        _jobs[job_id] = {"owner": user["id"], "status": "pending", "created": time.time()}

    agent_pool.submit(
        _run_web_job, current_app._get_current_object(), job_id, wa_id, name,
        message_body, message_type, _location_text(body.get("timezone")),
    )
    # Messages ahead of this one (WhatsApp or web) that the single worker must
    # finish first. A long queue is the usual reason a reply is slow to start.
    log.info(f"[job {job_id}] QUEUED for {wa_id} - {agent_pool._work_queue.qsize()} item(s) waiting in the agent queue")
    return jsonify({"job_id": job_id}), 202


@web_blueprint.route("/chat/<job_id>", methods=["GET"])
@web_auth_required
def get_chat_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        # Someone else's job id gets the same answer as a missing one.
        if not job or job["owner"] != g.web_user["id"]:
            log.warning(f"[job {job_id}] poll for unknown/expired job (server restarted?)")
            return jsonify({"status": "error", "error": "That reply has expired."}), 404
        return jsonify({k: job[k] for k in ("status", "reply", "error") if k in job})


def _user_text(raw):
    """oma_chat_history.user_message holds json.dumps(text) for text messages,
    and the model's plain-text description for photos."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return "📷 Sent a photo"
    if isinstance(value, str):
        return "📷 Sent a photo" if value in ("[media message]", "[unserialisable message]") else value
    return "📷 Sent a photo"


@web_blueprint.route("/history", methods=["GET"])
@web_auth_required
def get_history():
    session = Session()
    try:
        user_id, _, _ = resolve_oma_user(session, g.web_user)
        rows = (session.query(OmaChatHistory)
                .filter(OmaChatHistory.user_id == user_id)
                .order_by(OmaChatHistory.timestamp.desc(), OmaChatHistory.id.desc())
                .limit(HISTORY_LIMIT)
                .all())
        messages = []
        for r in reversed(rows):
            when = _iso(r.timestamp)
            ch = r.channel or channel.WHATSAPP
            messages.append({"id": f"u{r.id}", "role": "user", "channel": ch,
                             "text": _user_text(r.user_message), "created_at": when})
            messages.append({"id": f"o{r.id}", "role": "oma", "channel": ch,
                             "text": r.agent_response, "created_at": when})
        return jsonify({"messages": messages})
    except Exception as e:
        session.rollback()
        logging.error(f"web history failed: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Couldn't load your conversation."}), 500
    finally:
        session.close()


@web_blueprint.route("/documents", methods=["GET"])
@web_auth_required
def get_documents():
    session = Session()
    try:
        user_id, _, _ = resolve_oma_user(session, g.web_user)
        rows = (session.query(OmaUserDocument)
                .filter(OmaUserDocument.user_id == user_id)
                .order_by(OmaUserDocument.created_at.desc())
                .limit(50)
                .all())
        documents = []
        for d in rows:
            url, err = s3_storage.presigned_url(d.s3_key)
            documents.append({
                "id": d.id, "description": d.description, "mime_type": d.mime_type,
                "created_at": _iso(d.created_at), "url": None if err else url,
            })
        return jsonify({"documents": documents})
    except Exception as e:
        session.rollback()
        logging.error(f"web documents failed: {e}\n{traceback.format_exc()}")
        return jsonify({"message": "Couldn't load your documents."}), 500
    finally:
        session.close()
