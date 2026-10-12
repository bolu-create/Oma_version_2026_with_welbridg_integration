# file: app.py (your existing file, modified)
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import base64
import requests
from dotenv import load_dotenv
import os
import threading
import boto3
import uuid
import boto3
from botocore.exceptions import NoCredentialsError
from twilio_refined_1 import generate_response # your generator

load_dotenv()
app = Flask(__name__)

IMGBB_API_KEY = os.getenv('IMGBB_API_KEY')
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # e.g. 'whatsapp:+1415xxxxxxx'

BUCKET_NAME = os.getenv("BUCKET_NAME")
OBJECT_NAME = os.getenv("OBJECT_NAME")


s3 = boto3.client("s3", region_name="eu-north-1") 


def generate_presigned_url(bucket_name, object_name, expiration=3600):
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expiration
        )
        return url
    except NoCredentialsError:
        return None




def upload_file_to_s3(file_base64, bucket_name, object_name, content_type):
    """
    Uploads a base64-encoded file to S3 with the correct content type.

    :param file_base64: base64 string of the file content
    :param bucket_name: your S3 bucket name
    :param object_name: the S3 object key (path + filename)
    :param content_type: MIME type, e.g. "image/png", "image/jpeg", "application/pdf"
    :return: Public (or presigned) URL of the uploaded file
    """
    # Decode base64 string into raw bytes
    file_bytes = base64.b64decode(file_base64)

    # Upload to S3
    s3.put_object(
        Bucket=bucket_name,
        Key=object_name,
        Body=file_bytes,
        ContentType=content_type
    )

    # Return public S3 URL (assuming bucket is public, otherwise use presigned URL)
    return f"https://{bucket_name}.s3.eu-north-1.amazonaws.com/{object_name}"





def send_whatsapp_reply(to_number, body_text, media_url=None):
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    kwargs = {
        "body": body_text,
        "from_": TWILIO_WHATSAPP_NUMBER,
        "to": f"whatsapp:+{to_number}"
    }
    # If you want to send media back via Twilio:
    if media_url:
        kwargs["media_url"] = [media_url]
    client.messages.create(**kwargs)



def process_in_background(payload):
    """
    payload is a dict with all info needed to finish processing.
    This runs in a background thread.
    """
    try:
        sender = payload["sender"]
        profile_name = payload.get("profile_name", "")
        num_media = payload.get("num_media", 0)
        media_type = payload.get("media_type")
        media_url = payload.get("media_url")
        
        
        content_type = media_type or "image/png"
        extension = content_type.split("/")[-1]  # e.g., "png", "jpeg", "pdf"
        object_name = f"uploads/{sender}/{uuid.uuid4()}.{extension}"
        
        # 1) If there's media, fetch and upload to imgbb
        message_obj = None
        if num_media > 0 and media_url:
            print("YEAHHHHHH GOT HERE!!!!!!!!!!!!!!!!!")
            media_resp = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            media_resp.raise_for_status()
            file_data = media_resp.content
            b64 = base64.b64encode(file_data).decode("utf-8")
            
            #my_media_url = upload_to_imgbb(b64)
            my_media_url = upload_file_to_s3(b64, BUCKET_NAME, object_name, content_type)
            presigned_url = generate_presigned_url(BUCKET_NAME, object_name, expiration=604800)
            
            print(F"MEDIA_URL:->>>>  {presigned_url}")
            
            message_obj = {"type": "image_url", "image_url": {"url": presigned_url}}
            media_type_used = media_type
        else:
            # plain text
            message_obj = {"type": "text", "text": payload.get("body_text","")}
            media_type_used = "text"

        # 2) run your heavy generate_response_test
        response_text = generate_response(message_obj, media_type_used, sender, profile_name)

        # 3) Use Twilio REST API to send the reply (outbound message)
        send_whatsapp_reply(sender, response_text)

    except Exception as e:
        # Log errors — don't raise (thread would die)
        print("Background worker error:", e)





@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    # Parse incoming
    num_media = int(request.values.get("NumMedia", 0))
    #sender = request.values.get("From", "").lstrip("whatsapp:+")
    sender = request.values.get('From', '').lstrip("whatsapp:+")
    profile_name = request.values.get("ProfileName", "")
    media_url = request.values.get("MediaUrl0")
    media_type = request.values.get("MediaContentType0")
    body_text = request.values.get("Body", "")


    # Build payload for background worker
    payload = {
        "num_media": num_media,
        "media_url": media_url,
        "media_type": media_type,
        "body_text": body_text,
        "sender": sender,
        "profile_name": profile_name
    }

    # Start background thread (daemon so it won't block process exit)
    t = threading.Thread(target=process_in_background, args=(payload,), daemon=True)
    t.start()

    # Immediate ACK to Twilio — no TwiML message sent right now.
    # Twilio will get 200 and stop waiting; your thread continues and uses the REST API to reply later.
    return Response(status=200)





if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # fallback to 5000 if not defined
    app.run(host='0.0.0.0', port=port)
