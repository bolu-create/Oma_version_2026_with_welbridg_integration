import logging
import json
import traceback
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, request, jsonify, current_app

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

webhook_blueprint = Blueprint("webhook", __name__)


#def handle_message():
def handle_message_holder():
    """
    Handle incoming webhook events from the WhatsApp API.

    This function processes incoming WhatsApp messages and other events,
    such as delivery statuses. If the event is a valid message, it gets
    processed. If the incoming payload is not a recognized WhatsApp event,
    an error is returned.

    Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

    Returns:
        response: A tuple containing a JSON response and an HTTP status code.
    """
    body = request.get_json()
    # logging.info(f"request body: {body}")

    # Check if it's a WhatsApp status update
    if (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ):
        logging.info("Received a WhatsApp status update.")
        return jsonify({"status": "ok"}), 200

    try:
        if is_valid_whatsapp_message(body):
            process_whatsapp_message(body)
            return jsonify({"status": "ok"}), 200
        else:
            # if the request is not a WhatsApp API event, return an error
            return (
                jsonify({"status": "error", "message": "Not a WhatsApp API event"}),
                404,
            )
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON")
        return jsonify({"status": "error", "message": "Invalid JSON provided"}), 400


#............. Changing the text to avoid loops PART 1......................................
# ........................................................................................

processed_messages = set()

def get_unique_message_identifier(body):
    """Generate a unique identifier for each incoming message."""
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        
        if "messages" in value:
            message = value["messages"][0]
            message_id = message.get("id")
            timestamp = message.get("timestamp", "")
            return f"{message_id}:{timestamp}"  # Use ID + timestamp for uniqueness
    except (IndexError, KeyError):
        return None


# One bounded pool for the whole worker, instead of a fresh thread per message.
#
# max_workers=1 is deliberate, and it is about CONTEXT, not resources. The agent
# reads chat history at the start of a run and only commits the exchange at the
# end, 10-30s later. Anything running in parallel reads stale history, so a
# follow-up ("sorry, I meant Wednesday") gets answered without the message it is
# correcting. Worse: two quick messages from an unregistered user can both pass
# is_user_approved()==False and register them twice, since phone_number has no
# unique constraint.
#
# One worker plus a FIFO queue means messages are handled in arrival order, each
# one seeing the previous exchange already saved. Nothing is dropped - extra
# messages wait their turn.
#
# These threads are NOT daemons: Python joins them at interpreter exit, so a
# graceful shutdown finishes in-flight work instead of dropping it
# (--graceful-timeout in the Procfile is what gives them the time). A hard crash
# or SIGKILL still loses what is in flight; that needs a real broker.
#
# If concurrent users ever make sequential too slow, the next step is a lock
# keyed on wa_id: one user stays ordered, different users run in parallel.
agent_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oma-agent")


def process_in_background(app_obj, body):
    """
    Runs the agent off the request thread.

    Needs its own app context: send_message reads current_app.config, and
    current_app only exists inside a request unless we push one here.
    """
    with app_obj.app_context():
        try:
            process_whatsapp_message(body)
        except Exception as e:
            logging.error(f"Background processing failed: {e}\nFull Traceback:\n{traceback.format_exc()}")


def handle_message():
    body = request.get_json()
    unique_id = get_unique_message_identifier(body)

    if unique_id:
        if unique_id in processed_messages:
            logging.info(f"Duplicate message ignored: {unique_id}")
            return jsonify({"status": "ok"}), 200

        processed_messages.add(unique_id)

        # The agent takes tens of seconds (several LLM calls, emails, db work).
        # Meta gives up well before that and retries, which is what caused the
        # duplicate deliveries. Hand it to the pool and answer immediately -
        # same shape as process_in_background in run_aws_predesigned_v2.py.
        app_obj = current_app._get_current_object()
        agent_pool.submit(process_in_background, app_obj, body)

        return jsonify({"status": "ok"}), 200
    else:
        logging.info("No valid unique ID found; skipping.")
        return jsonify({"status": "ok"}), 200


#............................................................................................
# Required webhook verifictaion for WhatsApp
def verify():
    # Parse params from the webhook verification request
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    # Check if a token and mode were sent
    if mode and token:
        # Check the mode and token sent are correct
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            # Respond with 200 OK and challenge token from the request
            logging.info("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            # Responds with '403 Forbidden' if verify tokens do not match
            logging.info("VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verification failed"}), 403
    else:
        # Responds with '400 Bad Request' if verify tokens do not match
        logging.info("MISSING_PARAMETER")
        return jsonify({"status": "error", "message": "Missing parameters"}), 400


@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()

@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required
def webhook_post():
    return handle_message()



