"""
"Oma, keep this for me" — personal document storage.

Open to EVERY user, outreach staff and insurance users alike, which is why this
lives in its own module rather than inside functions_outreach: both the outreach
agent and the master agent import it.

Flow:
    save     user sends a photo + "save this, it's my clinic receipt"
    find     "send me the clinic receipt" -> matched, presigned, sent back

Scoping is by user_id and is enforced in every query here, not in the prompt. A
document is only ever findable by the person who saved it.

NOT gated by subscription yet — deliberately. There is no subscription flow to
gate against, and the categories aren't settled, so a stub boolean would just be
a guess in the wrong shape. The single call site to add it later is noted at
save_user_document().
"""

import os
import re
import time
import logging
from datetime import datetime

import requests

from db import OmaUserDocument, OmaUserRegistration
import s3_storage
import channel

# Words that carry no signal when matching a description. Kept small on purpose:
# over-filtering hurts more than it helps on descriptions this short.
_STOPWORDS = {
    "the", "a", "an", "my", "me", "of", "for", "that", "this", "it", "is", "was",
    "please", "send", "give", "back", "get", "find", "show", "from", "and", "to",
    "picture", "pic", "photo", "image", "document", "file", "oma",
}


# ── "Save that photo" ─────────────────────────────────────────────────────
# People often send a photo, talk about it, and only then say "keep that for
# me". The photo is no longer in that message, and nothing else holds the
# bytes (chat history stores only the model's description), so each sender's
# last photo is kept here for a short while. In memory, per process: fine for
# the single gunicorn worker; a restart only means asking them to resend.

RECENT_PHOTO_SECONDS = 30 * 60
_recent_photos = {}          # wa_id -> (time stored, data_uri)


def remember_photo(wa_id, data_uri):
    """Called for every incoming photo, on WhatsApp and the web."""
    if not (wa_id and data_uri):
        return
    now = time.time()
    for key in [k for k, (t, _) in _recent_photos.items() if now - t > RECENT_PHOTO_SECONDS]:
        del _recent_photos[key]
    _recent_photos[str(wa_id)] = (now, data_uri)


def recent_photo(wa_id):
    hit = _recent_photos.get(str(wa_id))
    if hit and time.time() - hit[0] <= RECENT_PHOTO_SECONDS:
        return hit[1]
    return None


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOPWORDS and len(w) > 1}


def send_whatsapp_image(to_number, image_url, caption=None):
    """Send an image back to a user via Meta's Cloud API.

    Meta fetches `image_url` itself at send time, so a short-lived R2 presigned
    link works and the bytes never pass through us twice.

    Duplicates the POST in functions_outreach.send_whatsapp_message rather than
    importing it: that module will import THIS one for its tools, and the cycle
    would break both.
    """
    try:
        token = os.getenv("ACCESS_TOKEN")
        version = os.getenv("VERSION")
        phone_number_id = os.getenv("PHONE_NUMBER_ID")
        if not (token and version and phone_number_id):
            logging.error("send_whatsapp_image: missing ACCESS_TOKEN / VERSION / PHONE_NUMBER_ID")
            return False

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": re.sub(r"\D", "", str(to_number)),
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption[:1024]

        resp = requests.post(
            f"https://graph.facebook.com/{version}/{phone_number_id}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {token}",
                     "Content-type": "application/json"},
            timeout=(10, 30),
        )
        if resp.status_code >= 400:
            # Meta fetching the link itself is the usual failure here — an
            # expired presign or a private object shows up as a 4xx from Meta,
            # not as an R2 error, so the body is the only way to tell.
            logging.error(f"send_whatsapp_image failed: HTTP {resp.status_code} body: {resp.text}")
            return False
        logging.info(f"send_whatsapp_image delivered to {to_number}")
        return True
    except Exception as e:
        logging.error(f"send_whatsapp_image error: {e}")
        return False


def save_user_document(session, user_id, wa_id, data_uri, description):
    """Store a photo the user asked Oma to keep.

    SUBSCRIPTION GATE GOES HERE when there is one to check.

    Returns a dict whose 'message' is what Oma says back.
    """
    try:
        # No photo in this message: fall back to the last one they sent
        # ("save that picture"), if it's recent.
        from_earlier = False
        if not data_uri:
            data_uri = recent_photo(wa_id)
            from_earlier = bool(data_uri)
        if not data_uri:
            return {"status": "error",
                    "message": ("I don't have a recent photo from you to save — send it again "
                                "and tell me what to call it.")}
        if not user_id:
            return {"status": "error",
                    "message": "I couldn't work out whose account to save that under."}

        description = (description or "").strip()
        if not description:
            return {"status": "needs_description",
                    "message": "Sure — what should I call it, so you can ask me for it later?"}

        key, err = s3_storage.upload_data_uri(
            f"user-documents/{wa_id}", data_uri,
            filename_hint=re.sub(r"[^a-z0-9]+", "-", description.lower())[:40].strip("-") or "doc",
        )
        if err:
            return {"status": "error", "message": err}

        data, mime = s3_storage.decode_data_uri(data_uri)
        doc = OmaUserDocument(
            user_id=user_id, wa_id=wa_id, s3_key=key,
            mime_type=mime, description=description,
            size_bytes=len(data) if data else None,
        )
        session.add(doc)
        session.commit()

        logging.info(f"save_user_document: {key} for user {user_id} — {description!r}"
                     f"{' (from their last photo)' if from_earlier else ''}")
        what = "your last photo" if from_earlier else "that"
        return {"status": "success",
                "message": f"Saved 📁 I've filed {what} as \"{description}\". Ask me for it any time."}
    except Exception as e:
        session.rollback()
        logging.error(f"save_user_document error: {e}")
        return {"status": "error", "message": "I couldn't save that just now — mind trying again?"}


def find_user_documents(session, user_id, query, limit=5):
    """Best matches for a rough description, for THIS user only.

    Scored on overlapping words rather than a single LIKE, so "the receipt from
    the clinic" still finds "clinic payment receipt". Deliberately simple: the
    corpus is one person's handful of documents, and FAISS embeddings would be
    a lot of machinery for that. Worth revisiting only if matching proves too
    literal in practice.
    """
    rows = (session.query(OmaUserDocument)
            .filter(OmaUserDocument.user_id == user_id)
            .order_by(OmaUserDocument.created_at.desc())
            .all())
    if not rows:
        return []

    wanted = _tokens(query)
    if not wanted:
        return rows[:limit]          # no usable words — most recent first

    scored = []
    for r in rows:
        overlap = len(wanted & _tokens(r.description))
        if overlap:
            scored.append((overlap, r))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [r for _, r in scored[:limit]]


def send_user_document(session, user_id, wa_id, query):
    """Find a saved document and send it back. 'message' is Oma's reply."""
    try:
        if not user_id:
            return {"status": "error",
                    "message": "I couldn't work out whose files to look in."}

        # An empty query used to fall through to "most recent first" and send
        # that file, so every time the agent wanted to see what was saved, the
        # user got their latest photo again. Sending needs a description of
        # what they asked for; with none, list instead and send nothing.
        if not (query or "").strip():
            return list_user_documents(session, user_id)

        matches = find_user_documents(session, user_id, query)

        if not matches:
            saved = session.query(OmaUserDocument).filter(
                OmaUserDocument.user_id == user_id).count()
            if saved == 0:
                return {"status": "empty",
                        "message": "You haven't asked me to save anything yet — send a photo and tell me what it is."}
            return {"status": "not_found",
                    "message": (f"I couldn't find anything matching that. You've got {saved} "
                                f"saved — describe it another way and I'll look again.")}

        # More than one plausible match: ask rather than send the wrong file.
        if len(matches) > 1:
            listed = ", ".join(f'"{m.description}"' for m in matches[:4])
            return {"status": "ambiguous",
                    "message": f"I've got a few that could match: {listed}. Which one?"}

        doc = matches[0]
        url, err = s3_storage.presigned_url(doc.s3_key)
        if err:
            return {"status": "error", "message": err}

        # On the web the picture is shown in the chat itself, so hand the link
        # back with the reply instead of sending it through WhatsApp.
        if channel.is_web():
            channel.add_attachment({
                "id": doc.id, "description": doc.description, "mime_type": doc.mime_type,
                "created_at": doc.created_at.isoformat() + "Z" if doc.created_at else None,
                "url": url,
            })
            logging.info(f"send_user_document: attached {doc.s3_key} to web reply")
            return {"status": "success", "sent": True,
                    "message": f"Here's \"{doc.description}\" 📎"}

        sent = send_whatsapp_image(wa_id, url, caption=doc.description)
        if not sent:
            return {"status": "error",
                    "message": "I found it but couldn't send it just now — try again in a moment?"}

        logging.info(f"send_user_document: sent {doc.s3_key} to {wa_id}")
        # The image goes as its own message, so this is only the accompanying
        # line. Keep it short — the picture is the answer.
        return {"status": "success", "sent": True,
                "message": f"Here's \"{doc.description}\" 📎"}
    except Exception as e:
        logging.error(f"send_user_document error: {e}")
        return {"status": "error", "message": "Something went wrong finding that — mind trying again?"}


def list_user_documents(session, user_id, limit=20):
    """Everything this user has saved — for "what have you got of mine?"."""
    try:
        rows = (session.query(OmaUserDocument)
                .filter(OmaUserDocument.user_id == user_id)
                .order_by(OmaUserDocument.created_at.desc())
                .limit(limit).all())
        if not rows:
            return {"status": "empty",
                    "message": "Nothing saved yet — send me a photo and tell me what it is."}
        listed = "\n".join(
            f"• {r.description}" + (f" ({r.created_at:%d %b})" if r.created_at else "")
            for r in rows)
        return {"status": "success",
                "message": f"Here's what I'm holding for you:\n{listed}"}
    except Exception as e:
        logging.error(f"list_user_documents error: {e}")
        return {"status": "error", "message": "Couldn't pull that list up just now."}
