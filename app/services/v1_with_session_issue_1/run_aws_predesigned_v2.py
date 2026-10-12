# file: app.py
from flask import Flask, request, Response
from twilio.rest import Client
import requests
from dotenv import load_dotenv
import os
import threading
import boto3
import uuid
from botocore.exceptions import NoCredentialsError
from twilio_refined_1 import generate_response  # your generator

load_dotenv() 
app = Flask(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
BUCKET_NAME = os.getenv("BUCKET_NAME")

s3 = boto3.client("s3", region_name="eu-north-1")


def generate_presigned_url(bucket_name, object_name, expiration=604800):  # default 7 days
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expiration
        )
    except NoCredentialsError:
        return None


def upload_file_to_s3(file_bytes, bucket_name, object_name, content_type):
    """Upload raw bytes (no base64 overhead) to S3."""
    s3.put_object(
        Bucket=bucket_name,
        Key=object_name,
        Body=file_bytes,
        ContentType=content_type
    )
    return f"https://{bucket_name}.s3.eu-north-1.amazonaws.com/{object_name}"


def send_whatsapp_reply(to_number, body_text, media_url=None):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    kwargs = {
        "body": body_text,
        "from_": TWILIO_WHATSAPP_NUMBER,
        "to": f"whatsapp:+{to_number}"
    }
    if media_url:
        kwargs["media_url"] = [media_url]
    client.messages.create(**kwargs)


def process_in_background(payload):
    """Heavy lifting runs here (background thread)."""
    try:
        sender = payload["sender"]
        profile_name = payload.get("profile_name", "")
        num_media = payload.get("num_media", 0)
        media_type = payload.get("media_type")
        media_url = payload.get("media_url")

        content_type = media_type or "image/png"
        extension = content_type.split("/")[-1]
        object_name = f"uploads/{sender}/{uuid.uuid4()}.{extension}"

        # If there's media, fetch and upload to S3
        if num_media > 0 and media_url:
            media_resp = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            media_resp.raise_for_status()
            file_data = media_resp.content  # already bytes

            upload_file_to_s3(file_data, BUCKET_NAME, object_name, content_type)
            presigned_url = generate_presigned_url(BUCKET_NAME, object_name, expiration=604800)

            message_obj = {"type": "image_url", "image_url": {"url": presigned_url}}
            media_type_used = media_type
        else:
            # Plain text
            message_obj = {"type": "text", "text": payload.get("body_text", "")}
            media_type_used = "text"

        # Generate AI response
        response_text = generate_response(message_obj, media_type_used, sender, profile_name)

        # Send back via Twilio
        send_whatsapp_reply(sender, response_text)

    except Exception as e:
        print("Background worker error:", e)


@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
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

    threading.Thread(target=process_in_background, args=(payload,), daemon=True).start()

    # Immediate ACK to Twilio
    return Response(status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
