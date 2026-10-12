"""
Cloudflare R2 storage for documents Oma is asked to keep — consent forms and
users' personal documents.

Kept deliberately thin and separate from the agent code so there is exactly one
place that knows about buckets, keys and credentials. The module keeps its old
name because R2 speaks the S3 API: boto3 is still the client, it just points at
Cloudflare's endpoint instead of AWS.

Configuration (Railway variables — never hardcode these):
    R2_ACCOUNT_ID         Cloudflare account ID (in the dashboard URL)
    R2_ACCESS_KEY_ID      from the R2 API token
    R2_SECRET_ACCESS_KEY  from the R2 API token
    R2_BUCKET_NAME        e.g. oma-documents

Nothing here logs the credentials.

Two rules this module exists to enforce:

1. The bucket is PRIVATE. Nothing is ever made public. Files come back out only
   through short-lived presigned URLs.
2. Those URLs are bearer tokens — anyone holding the link can fetch the file
   until it expires, and they end up sitting in WhatsApp threads. The default
   lifetime here is five minutes. Meta fetches media the moment you send it, so
   a short window costs nothing.
"""

import os
import base64
import logging

DEFAULT_PRESIGN_SECONDS = 300  # 5 minutes — see note above


def bucket_name():
    return os.getenv("R2_BUCKET_NAME")


def _client():
    """Build an R2 client, or return (None, error).

    Created on demand rather than at import: a missing credential should fail
    the one upload that needs it, not stop the whole app booting the way an
    import-time client would.
    """
    try:
        import boto3  # imported here so the app still starts without boto3
        from botocore.config import Config
    except ImportError:
        logging.error("s3_storage: boto3 is not installed")
        return None, "File storage isn't available right now."

    account_id = os.getenv("R2_ACCOUNT_ID")
    access_key = os.getenv("R2_ACCESS_KEY_ID")
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY")
    missing = [name for name, value in (
        ("R2_ACCOUNT_ID", account_id),
        ("R2_ACCESS_KEY_ID", access_key),
        ("R2_SECRET_ACCESS_KEY", secret_key),
        ("R2_BUCKET_NAME", bucket_name()),
    ) if not value]
    if missing:
        logging.error(f"s3_storage: not configured, missing {', '.join(missing)}")
        return None, "File storage isn't configured."

    try:
        return boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",  # R2 has no regions; "auto" is what it expects
            config=Config(
                signature_version="s3v4",
                # boto3 >= 1.36 adds checksum headers to every request by
                # default. Cloudflare recommends only sending them when the
                # operation requires it.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        ), None
    except Exception as e:
        logging.error(f"s3_storage: could not create client: {e}")
        return None, "File storage isn't available right now."


def decode_data_uri(data_uri):
    """'data:image/jpeg;base64,XXXX' -> (bytes, 'image/jpeg').

    Returns (None, None) on anything that isn't a data URI. Images reach the
    service layer already base64-encoded for the vision model, so this turns
    them back into bytes for storage rather than downloading twice.
    """
    try:
        if not isinstance(data_uri, str) or not data_uri.startswith("data:"):
            return None, None
        header, encoded = data_uri.split(",", 1)
        content_type = header[len("data:"):].split(";")[0] or "application/octet-stream"
        return base64.b64decode(encoded), content_type
    except Exception as e:
        logging.error(f"s3_storage.decode_data_uri failed: {e}")
        return None, None


def upload_bytes(key, data, content_type):
    """Store raw bytes at `key`. Returns (key, None) or (None, error_message)."""
    client, err = _client()
    if err:
        return None, err
    try:
        client.put_object(
            Bucket=bucket_name(),
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        logging.info(f"s3_storage: uploaded {key} ({len(data)} bytes, {content_type})")
        return key, None
    except Exception as e:
        logging.error(f"s3_storage: upload of {key} failed: {e}")
        return None, "I couldn't save that file just now."


def upload_data_uri(key_prefix, data_uri, filename_hint="file"):
    """Decode a data URI and store it under a generated key.

    Returns (key, None) or (None, error_message).
    """
    data, content_type = decode_data_uri(data_uri)
    if data is None:
        return None, "That doesn't look like a readable image."

    ext = (content_type.split("/")[-1] or "bin").replace("jpeg", "jpg")
    from datetime import datetime
    import uuid
    key = f"{key_prefix.rstrip('/')}/{datetime.utcnow():%Y/%m/%d}/{filename_hint}-{uuid.uuid4().hex[:12]}.{ext}"
    return upload_bytes(key, data, content_type)


def presigned_url(key, expires=DEFAULT_PRESIGN_SECONDS):
    """A short-lived read URL for `key`. Returns (url, None) or (None, error)."""
    client, err = _client()
    if err:
        return None, err
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name(), "Key": key},
            ExpiresIn=int(expires),
        )
        return url, None
    except Exception as e:
        logging.error(f"s3_storage: presign of {key} failed: {e}")
        return None, "I couldn't retrieve that file just now."


def delete_object(key):
    """Remove a stored file. Used when a record it belongs to is deleted."""
    client, err = _client()
    if err:
        return False, err
    try:
        client.delete_object(Bucket=bucket_name(), Key=key)
        logging.info(f"s3_storage: deleted {key}")
        return True, None
    except Exception as e:
        logging.error(f"s3_storage: delete of {key} failed: {e}")
        return False, "Could not delete that file."
