import os
import json
import logging
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_credentials() -> Credentials:
    """
    Load credentials from environment variables.
    TOKEN_JSON should be the full contents of token.json (as a string).
    """
    token_data = os.environ.get("TOKEN_JSON")
    if not token_data:
        raise RuntimeError("TOKEN_JSON environment variable is not set.")

    creds = Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        logger.info("Refreshed YouTube OAuth token.")

    return creds


def upload_video(file_path: str, title: str, privacy: str = "unlisted") -> str:
    """
    Upload a video file to YouTube.
    Returns the YouTube video ID.
    """
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": "Uploaded via Telegram Bot",
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    media = MediaFileUpload(file_path, mimetype="video/*", resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Upload progress: {int(status.progress() * 100)}%")

    video_id = response["id"]
    logger.info(f"Upload complete: https://www.youtube.com/watch?v={video_id}")
    return video_id
