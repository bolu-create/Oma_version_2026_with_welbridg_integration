import logging
from flask import current_app, jsonify
import json
import requests
import random

#from app.services.agent_retriever_ctx import generate_responseee
#from app.services.agent_chain_deepseek import generate_response
#from app.services.chain_only_with_context import generate_response
#from app.services.chain_only_with_stage_gate_json import generate_response#
#from app.services.chain_only_refined_user_id_two import generate_response
#from app.services.chain_only_user_id_no_hm import generate_response
#from app.services.chain_only_refined_user_id_three import generate_response
#from app.services.chain_only_booking_prompt_cleaned import generate_response

#from app.services.chain_only_bookings import generate_response
#from app.services.fresh_start import generate_response
#from app.services.fresh_start_o1 import generate_response
#from app.services.fresh_Version_1 import generate_response
#from app.services.fresh_Version_reminder_2 import generate_response

#from app.services.fresh_version_reminder_with_email import generate_response
#from app.services.fresh_version_reminder_with_nationality import generate_response
#from app.services.fresh_version_with_nationality_and_nation_support import generate_response
# Session comes from the same db module the service helpers were star-imported
# from, so the session handed to generate_response is the one they expect.
from app.services.fresh_version_with_new_db import generate_response, generate_response_test, Session
import documents  # on sys.path via app.services, same module instance the agents use

#from app.services.oma_sql_fix import generate_response  # This did not work






import re

def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")


def get_text_message_input(recipient, text):
    return json.dumps(
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
    )

"""
def generate_response(response):
    # Return text in uppercase
    return response.upper()
"""

## .................I will also Need this .......................
def send_message(data):
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }

    url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

    try:
        # (connect, read). A flat timeout=10 was tripping on Meta simply being
        # slow to answer, which cost the user their reply. Splitting the two
        # keeps a short leash on connecting while allowing a slow response.
        response = requests.post(
            url, data=data, headers=headers, timeout=(10, 30)
        )
        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
    except requests.ConnectTimeout:
        # The connection was never established, so Meta definitely never saw
        # this message - retrying cannot duplicate it. Contrast with a read
        # timeout below, where the request may well have been delivered.
        logging.warning("Connect timeout sending message — retrying once")
        try:
            response = requests.post(url, data=data, headers=headers, timeout=(10, 30))
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Retry after connect timeout also failed: {e}")
            return jsonify({"status": "error", "message": "Request timed out"}), 408
        else:
            log_http_response(response)
            return response
    except requests.Timeout:
        # Read timeout: the request WAS sent and Meta may have processed it. We
        # deliberately do not retry — a resend here is how people end up getting
        # the same reply twice. Better one missing message than a duplicate we
        # can't detect.
        logging.error("Read timeout sending message — not retrying, Meta may have "
                      "delivered it already")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except (
        requests.RequestException
    ) as e:  # This will catch any general request exception
        # Meta explains the real reason in the response body (error.code,
        # error.message, error_data.details). raise_for_status() only reports
        # the status line, so without this the actual cause was discarded and a
        # 403 told us nothing about whether it was the token, the recipient
        # allow-list, or a rate limit.
        meta_status = getattr(e.response, "status_code", None)
        meta_body = getattr(e.response, "text", None)
        logging.error(
            f"Request failed due to: {e}\n"
            f"Meta HTTP {meta_status} body: {meta_body}"
        )
        return jsonify({"status": "error", "message": "Failed to send message"}), 500
    else:
        # Process the response as normal
        log_http_response(response)
        return response

## .................I will Need this .......................
def process_text_for_whatsapp(text):
    
    #..............New portion I am adding so It doesn't bug out and not respond..................
    if not isinstance(text, str):  # Check if text is None or not a string
        logging.warning("Received None or invalid type for text")
        my_list = [
                    "Sorry, one message at a time, didn't quite catch that, you can come again.", 
                    "Let's take it bit by bit, send me one message at a time.", 
                    "Oh hold on, come again, but send one message at a time.", 
                    "I missed that, send it again but just one message at a time.", 
                    "come again, but one message at a time, please.", 
                    "Whoops, didn't catch that try sending it again, just one message at a time.", 
                    "Slow down a bit, I need you to send just one message at a time, come again.",  
                    "Let's try again, send just one message at a time so I can follow better.", 
                  ]

        return random.choice(my_list)
    #.............................................................
    
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text



# Process handler containing timestamp
from datetime import datetime, timezone
import traceback
import base64

# Meta caps media at 5MB. We stop well short: base64 inflates by ~33%, and the
# encoded string travels in the model request body on every turn it stays in
# context. Anything bigger and we ask for a smaller photo instead of silently
# failing somewhere deeper.
MAX_IMAGE_BYTES = 3 * 1024 * 1024

# Instant, canned, zero-cost. Deliberately NOT model-generated: the point is to
# land immediately, and an LLM call would add the very latency it exists to hide.
IMAGE_ACK_REPLIES = [
    "Got your pic 📸 taking a look…",
    "Photo received 👀 give me a sec…",
    "Nice, I can see it — reading it now 🔍",
    "Got it! Looking at that now 📸",
]


def summarise_body(message_body):
    """A short, log-safe description of what the user sent.

    message_body may be a plain string or the content-part list used for images.
    An image part holds a base64 data URI that is megabytes long, so it must
    never reach the logs verbatim.
    """
    if isinstance(message_body, str):
        return message_body[:200]
    if isinstance(message_body, list):
        bits = []
        for part in message_body:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                bits.append(f"text: {str(part.get('text', ''))[:120]}")
            elif part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                mime = url.split(";")[0].replace("data:", "") if url.startswith("data:") else "image"
                bits.append(f"<{mime}, {len(url)} b64 chars>")
        return " + ".join(bits) or "<empty content list>"
    return f"<{type(message_body).__name__}>"


def fetch_media_as_data_uri(media_id):
    """Download a WhatsApp media item and return it as a base64 data URI.

    Meta hands the webhook a media *id*, not a URL, and it takes two calls:
      1. GET /{version}/{media_id}      -> JSON with a short-lived 'url'
      2. GET that url WITH the bearer   -> the actual bytes
    The url is authenticated and expires in minutes, so it can't be passed to
    the model directly. We inline the bytes instead, which is also why no S3
    bucket or presigned-URL step is needed here (that was a Twilio-era
    workaround, because Twilio's media URL wasn't fetchable by the model).

    Returns (data_uri, error_message). Exactly one is None.
    """
    try:
        token = current_app.config["ACCESS_TOKEN"]
        version = current_app.config["VERSION"]
        headers = {"Authorization": f"Bearer {token}"}

        meta = requests.get(
            f"https://graph.facebook.com/{version}/{media_id}",
            headers=headers, timeout=15,
        )
        if meta.status_code >= 400:
            logging.error(f"media lookup failed for {media_id}: "
                          f"HTTP {meta.status_code} body: {meta.text}")
            return None, "I couldn't fetch that image from WhatsApp."

        info = meta.json()
        media_url = info.get("url")
        mime_type = info.get("mime_type") or "image/jpeg"
        if not media_url:
            logging.error(f"media lookup for {media_id} returned no url: {info}")
            return None, "I couldn't fetch that image from WhatsApp."

        # The CDN url still requires the bearer token.
        binary = requests.get(media_url, headers=headers, timeout=30)
        if binary.status_code >= 400:
            logging.error(f"media download failed for {media_id}: "
                          f"HTTP {binary.status_code} body: {binary.text[:300]}")
            return None, "I couldn't download that image."

        raw = binary.content
        if len(raw) > MAX_IMAGE_BYTES:
            logging.warning(f"media {media_id} too large: {len(raw)} bytes")
            return None, ("That image is a bit too large for me to read 😅 — could you send "
                          "a smaller or more compressed version?")

        encoded = base64.b64encode(raw).decode("utf-8")
        logging.info(f"media {media_id} fetched: {len(raw)} bytes, {mime_type}")
        return f"data:{mime_type};base64,{encoded}", None

    except Exception as e:
        logging.error(f"fetch_media_as_data_uri error for {media_id}: {e}\n{traceback.format_exc()}")
        return None, "Something went wrong reading that image."


def process_whatsapp_message(body):
    
    #logging.info(f"Message body: {body}"))
    print(f"Message body: {body}")
    
    try:
        # Extract contacts information
        contacts = body["entry"][0]["changes"][0]["value"]["contacts"][0]
        wa_id = contacts.get("wa_id")
        name = contacts.get("profile", {}).get("name")
        my_wa_id = "+" + wa_id
        print(my_wa_id)

        # Extract messages list
        messages = body["entry"][0]["changes"][0]["value"].get("messages", [])

        for message in messages:
            wa_type = message.get("type", "text")

            # ── Work out what the user actually sent ──────────────────────────
            # message_type is what generate_response branches on: "text" for
            # text, or the image mime ("image/jpeg" / "image/png") which makes it
            # run image_explainer.
            if wa_type == "image":
                media_id = (message.get("image") or {}).get("id")
                if not media_id:
                    logging.warning(f"Image message with no media id: {message}")
                    continue

                # Acknowledge BEFORE the slow part. With a photo the user can't
                # tell whether it even uploaded, and the download plus vision
                # call takes seconds. Text replies go without an ack because
                # there's nothing ambiguous about a message that visibly sent.
                send_message(get_text_message_input(my_wa_id, random.choice(IMAGE_ACK_REPLIES)))

                data_uri, err = fetch_media_as_data_uri(media_id)
                if err:
                    send_message(get_text_message_input(my_wa_id, err))
                    continue

                message_type = (message.get("image") or {}).get("mime_type") or "image/jpeg"
                # Lets "save that photo" in a later message still find it.
                documents.remember_photo(wa_id, data_uri)

                # The content-part list the agents were built for. A caption
                # rides along as a text part so "is this rash serious?" keeps
                # its context instead of arriving as a bare photo.
                caption = (message.get("image") or {}).get("caption")
                message_body = []
                if caption:
                    message_body.append({"type": "text", "text": caption})
                message_body.append({"type": "image_url", "image_url": {"url": data_uri}})

            else:
                message_type = wa_type
                message_body = message.get("text", {}).get("body")
                if not message_body:
                    # Stickers, audio, documents, locations - nothing can read
                    # them yet, so say so rather than going quiet.
                    logging.warning(f"Unsupported message type '{wa_type}': {message}")
                    send_message(get_text_message_input(
                        my_wa_id,
                        "I can only read text and photos at the moment 😅 — mind sending it that way?"))
                    continue

            # Extract the timestamp (UNIX epoch format, UTC)
            timestamp = message.get("timestamp")
            if timestamp:
                timestamp = int(timestamp)  # Convert to integer
                utc_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                print(f"Message received at (UTC): {utc_time}")
            else:
                logging.warning(f"No timestamp found for message: {message}")

            #.......... TEST MODE — echoes back, no db and no LLM ..........
            # Confirms WhatsApp is talking to us and we can reply. Swap the two
            # blocks below to go back to the real agent.
            #response = generate_response_test(message_body, message_type, wa_id, name)

            #.......... LIVE AGENT ..........
            # generate_response wants a db session first, and the message type
            # ("text", "image", ...) so it knows whether to describe an image.
            session = Session()
            try:
                response = generate_response(session, message_body, message_type, wa_id, name)
            finally:
                session.close()  # close() is idempotent, so the closes inside are fine

            response = process_text_for_whatsapp(response)
            data = get_text_message_input(my_wa_id, response)
            send_result = send_message(data)

            # send_message returns a requests.Response on success, or a Flask
            # (json, status) tuple on failure. This used to log "Processed and
            # sent" either way, so a timeout looked identical to a delivered
            # reply and the user's silence had no matching line in the log.
            # Never log message_body directly - for an image it is a multi-MB
            # base64 string that would swamp the deploy logs.
            delivered = getattr(send_result, "status_code", 599) < 400
            if delivered:
                logging.info(f"Processed and SENT response for message: {summarise_body(message_body)}")
            else:
                logging.error(
                    f"Response generated but NOT DELIVERED for message: "
                    f"{summarise_body(message_body)} — the user got nothing")
    

    except KeyError as e:
        logging.error(f"KeyError while processing message: {e}\nFull Traceback:\n{traceback.format_exc()}")
    except Exception as e:
        logging.error(f"Unexpected error while processing messages: {e}\nFull Traceback:\n{traceback.format_exc()}")

    
    """
    except KeyError as e:
        logging.error(f"KeyError while processing message: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while processing messages: {e}")
    """




"""Without the timestamp
#...................NEW CODE BLOCK AIMED AT ALLOWING HANDLING MULTIPLE MESSAGES.........................
def process_whatsapp_message(body):
    try:
        # Extract contacts information (assuming it's consistent for all messages in the payload)
        contacts = body["entry"][0]["changes"][0]["value"]["contacts"][0]
        wa_id = contacts.get("wa_id")
        name = contacts.get("profile", {}).get("name")
        my_wa_id = "+" + wa_id
        print(my_wa_id)
        #print(current_app.config["RECIPIENT_WAID"])
       
        # Extract messages list
        messages = body["entry"][0]["changes"][0]["value"].get("messages", [])

        # Iterate through each message in the payload
        for message in messages:
            # Safely extract message body
            message_body = message.get("text", {}).get("body")
            if not message_body:
                logging.warning(f"Message body is None or invalid: {message}")
                continue  # Skip this message if body is missing or invalid

            # Generate response (you can include wa_id and name in the agent for personalized responses)
            response = generate_response(message_body, wa_id, name)

            # Process response text for WhatsApp formatting
            response = process_text_for_whatsapp(response)

            # Prepare and send the message
            #data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
            data = get_text_message_input(my_wa_id, response)
            send_message(data)

            logging.info(f"Processed and sent response for message: {message_body}")

    except KeyError as e:
        logging.error(f"KeyError while processing message: {e}")
    except Exception as e:
        logging.error(f"Unexpected error while processing messages: {e}")

"""

"""
#........................ORIGINAL CODE BLOCK..............................
def process_whatsapp_message_holder(body):
    wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]

    message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    message_body = message["text"]["body"]
    
    #.............from here down is what I will need in mine....................
    # TODO: implement custom function here
    #response = generate_response(message_body)

    # OpenAI Integration
    response = generate_response(message_body, wa_id, name) #If I have the wa_id and name I can use that in my agent for a reasonable query. These can be appended to my prompt
    response = process_text_for_whatsapp(response)

    data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
    send_message(data)
"""


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
