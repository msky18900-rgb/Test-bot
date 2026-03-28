import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)


def upload_video_with_creds(file_path: str, title: str, creds: Credentials, privacy: str = "unlisted") -> str:
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": "Uploaded via Telegram Bot",
            "categoryId": "22",
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
