# file: tasks.py
import os
import uuid
import requests
import boto3
from twilio.rest import Client
from dotenv import load_dotenv
from celery import Celery
from botocore.exceptions import NoCredentialsError
from twilio_refined_1 import generate_response, generate_response_test # your AI generator

load_dotenv()


# SAVED INFORMATION
# celery -A celery_tasks.celery worker --loglevel=info

# Config
#This defaults to renders redis provided URL 
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# S3 client
s3 = boto3.client("s3", region_name="eu-north-1")

# Celery app
celery = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)


def generate_presigned_url(bucket_name, object_name, expiration=604800):  # 7 days
    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_name},
            ExpiresIn=expiration
        )
    except NoCredentialsError:
        return None


def upload_file_to_s3(file_bytes, bucket_name, object_name, content_type):
    """Upload raw bytes to S3."""
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


@celery.task
def process_in_background(payload):
    """Background task executed by Celery workers."""
    
    print("BOLU: 1 This Celery task got Here!!!!!!!!!!!!!!!!")
    try:
        sender = payload["sender"]
        profile_name = payload.get("profile_name", "")
        num_media = payload.get("num_media", 0)
        media_type = payload.get("media_type")
        media_url = payload.get("media_url")
        body_text = payload.get("body_text")
        body_text_len = len(body_text)

        content_type = media_type or "image/png"
        extension = content_type.split("/")[-1]
        object_name = f"uploads/{sender}/{uuid.uuid4()}.{extension}"
        
        print("BOLU: 2 This Celery task got Here!!!!!!!!!!!!!!!!")
        



        if num_media > 0 and media_url and body_text_len == 0:
            # download media from Twilio
            media_resp = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            media_resp.raise_for_status()
            file_data = media_resp.content

            upload_file_to_s3(file_data, BUCKET_NAME, object_name, content_type)
            presigned_url = generate_presigned_url(BUCKET_NAME, object_name)

            message_obj = [{"type": "image_url", "image_url": {"url": presigned_url}}]
            media_type_used = media_type
            
            
            
            
        elif num_media > 0 and media_url and body_text_len > 0:
            # download media from Twilio
            media_resp = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            media_resp.raise_for_status()
            file_data = media_resp.content

            upload_file_to_s3(file_data, BUCKET_NAME, object_name, content_type)
            presigned_url = generate_presigned_url(BUCKET_NAME, object_name)

            message_obj = [{"type": "text", "text": body_text}, {"type": "image_url", "image_url": {"url": presigned_url}}]
            media_type_used = media_type
            
            
            
            
        else:
            # text only
            message_obj = [{"type": "text", "text": payload.get("body_text", "")}]
            media_type_used = "text"



        # Generate AI response
        response_text = generate_response(message_obj, media_type_used, sender, profile_name)
        #response_text = generate_response_test(message_obj, media_type_used, sender, profile_name)
        

        print("BOLU: 3 This Celery task got Here!!!!!!!!!!!!!!!!")
        print(f"RESPONSE: {response_text}")

        # Send reply
        send_whatsapp_reply(sender, response_text)

    except Exception as e:
        print("Celery worker error:", e)
