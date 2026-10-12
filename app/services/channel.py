"""
Which channel the message being handled came in on: "whatsapp" or "web".

The agent code was written for WhatsApp and a few places act on that directly
(sending a saved photo through Meta, guessing the country from the phone
number). Rather than thread a channel argument through every function between
the request and those places, the web handler sets it here for the duration of
one run and the few channel-aware spots read it.

Contextvars are per thread, and each run happens on a single agent_pool worker
thread, so one run can't see another's channel. Anything that never calls
start() sees the WhatsApp defaults, which keeps the WhatsApp path unchanged.
"""

from contextvars import ContextVar

WHATSAPP = "whatsapp"
WEB = "web"

_state = ContextVar("oma_channel_state", default=None)


def start(name, country=None):
    """Begin a run on `name`. Returns a token for finish()."""
    return _state.set({"channel": name, "country": country, "attachments": []})


def finish(token):
    _state.reset(token)


def current():
    s = _state.get()
    return s["channel"] if s else WHATSAPP


def is_web():
    return current() == WEB


def country_override():
    """Location text supplied by the web client (from the browser's time zone),
    used instead of guessing a country from a WhatsApp number."""
    s = _state.get()
    return s["country"] if s else None


def add_attachment(item):
    """A document to show alongside the reply on the web."""
    s = _state.get()
    if s is not None:
        s["attachments"].append(item)


def attachments():
    s = _state.get()
    return list(s["attachments"]) if s else []
