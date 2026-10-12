# file: app.py
from flask import Flask, request, Response
from twilio.rest import Client
from dotenv import load_dotenv
import os
from celery_tasks import process_in_background   # import celery task
from twilio.twiml.messaging_response import MessagingResponse
import random


load_dotenv()
app = Flask(__name__)


# Deployment String


# Twilio settings
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Redis URL (local or Render)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    """Webhook called by Twilio when a WhatsApp message is received"""
    num_media = int(request.values.get("NumMedia", 0))
    sender = request.values.get("From", "").lstrip("whatsapp:+")
    profile_name = request.values.get("ProfileName", "")
    media_url = request.values.get("MediaUrl0")
    media_type = request.values.get("MediaContentType0")
    body_text = request.values.get("Body", "")

    payload = {
        "num_media": num_media,
        "media_url": media_url,
        "media_type": media_type,
        "body_text": body_text,
        "sender": sender,
        "profile_name": profile_name
    }

    # instead of threading, push task to Celery
    print(payload)
    process_in_background.delay(payload)



    if payload['media_type'] != None: 
        
        ack_messages = [
            "Message received. Gimme a min to check that.",
            "Okay, got your image, give me a moment.",
            "Thanks, I’ve got it. Hold on a sec while I take a look.",
            "👌 Got your message, checking it out now.",
            "Alright, I see what you sent. Give me a moment to process.",
            "Got it ✅ I’ll work on this and get back to you shortly.",
            "Thanks for sending that over, just a moment while I review.",
            "Okay, I’ve received it. Let me dig in for a bit.",
            "👍 Your message came through. Working on it now.",
        ]
        # Build TwiML response
        chosen_reply = random.choice(ack_messages)
        resp = MessagingResponse()
        resp.message(chosen_reply)
        return Response(str(resp), mimetype="application/xml")
    
    else:
        # Immediate ACK to Twilio
        return Response(status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
