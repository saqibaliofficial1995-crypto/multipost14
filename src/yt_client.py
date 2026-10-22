"""
YouTube Data API v3 client for Channel 14 (Donna Gonzales).
Includes channel inspection, metadata retrieval, and resumable uploads with safety gates.
"""

import time
from typing import Any, Dict
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


def get_youtube_service(credentials):
    """Build and return YouTube Data API v3 service."""
    return build("youtube", "v3", credentials=credentials)


def get_channel_info(service) -> Dict[str, Any]:
    """
    Fetch authenticated channel details: ID, title, uploads playlist, video count, subscriber count, and brandingSettings.
    """
    res = service.channels().list(
        part="snippet,status,statistics,contentDetails,brandingSettings",
        mine=True,
    ).execute()

    items = res.get("items", [])
    if not items:
        raise ValueError("No channel found for current authenticated user.")

    ch = items[0]
    snippet = ch.get("snippet", {})
    statistics = ch.get("statistics", {})
    content_details = ch.get("contentDetails", {})
    branding = ch.get("brandingSettings", {})

    return {
        "id": ch.get("id"),
        "title": snippet.get("title"),
        "custom_url": snippet.get("customUrl"),
        "uploads_playlist": content_details.get("relatedPlaylists", {}).get("uploads"),
        "video_count": int(statistics.get("videoCount", 0)),
        "subscriber_count": int(statistics.get("subscriberCount", 0)),
        "view_count": int(statistics.get("viewCount", 0)),
        "brandingSettings": branding,
        "raw": ch,
    }


def upload_video(
    service,
    file_path: str,
    metadata: Dict[str, Any],
    privacy_status: str = "public",
    made_for_kids: bool = False,
) -> Dict[str, Any]:
    """
    Perform resumable video upload with safety verification.
    """
    # HARD SAFETY GATE
    if metadata.get("path") != "video_ai_gemini":
        raise ValueError("Safety Gate Rejection: metadata['path'] must equal 'video_ai_gemini'")

    body = {
        "snippet": {
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "tags": metadata.get("tags", []),
            "categoryId": "22",  # People & Blogs / Lifestyle
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    media = MediaFileUpload(
        file_path,
        chunksize=10 * 1024 * 1024,
        resumable=True,
        mimetype="video/*",
    )

    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retry_count = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"[upload] Upload progress: {progress}%")
        except HttpError as e:
            if e.resp.status in [500, 502, 503, 504]:
                retry_count += 1
                if retry_count > 5:
                    raise
                wait_time = 2 ** retry_count
                print(f"[upload] Retrying upload after HTTP {e.resp.status} (attempt {retry_count}). Waiting {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise

    video_id = response.get("id")
    print(f"[upload] Video published successfully. Video ID: {video_id}")
    return response