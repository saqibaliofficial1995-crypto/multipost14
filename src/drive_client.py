"""
Google Drive client module for Channel 14.
Handles file pagination, folder management, downloading, and moving processed files.
"""

import io
from pathlib import Path
from typing import Any, Dict, List, Tuple

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def get_drive_service(credentials):
    """Build and return Google Drive v3 service."""
    return build("drive", "v3", credentials=credentials)


def list_drive_files(service, folder_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    List all files in the given folder with complete pagination.
    Splits items into video files and non-conforming files.
    """
    query = f"'{folder_id}' in parents and trashed = false"
    page_token = None
    all_files: List[Dict[str, Any]] = []

    while True:
        results = service.files().list(
            q=query,
            pageSize=100,
            pageToken=page_token,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
        ).execute()

        files = results.get("files", [])
        all_files.extend(files)

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    video_files: List[Dict[str, Any]] = []
    non_conforming: List[Dict[str, Any]] = []

    for f in all_files:
        name = f.get("name", "")
        mime = f.get("mimeType", "")
        ext = Path(name).suffix.lower()

        is_video = ext in VIDEO_EXTENSIONS or mime.startswith("video/")
        if is_video:
            video_files.append(f)
        else:
            non_conforming.append(f)

    return video_files, non_conforming


def get_or_create_uploaded_folder(service, parent_folder_id: str) -> str:
    """
    Find or create the 'Uploaded' subfolder inside the parent folder.
    Returns the uploaded folder ID.
    """
    query = (
        f"'{parent_folder_id}' in parents and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "name = 'Uploaded' and "
        "trashed = false"
    )
    response = service.files().list(q=query, fields="files(id, name)").execute()
    files = response.get("files", [])

    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": "Uploaded",
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    return folder.get("id")


def download_file(service, file_id: str, dest_path: str) -> str:
    """
    Download a file from Google Drive in chunks.
    """
    request = service.files().get_media(fileId=file_id)
    dest_path_obj = Path(dest_path)
    dest_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with io.FileIO(dest_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()

    return dest_path


def move_to_uploaded(service, file_id: str, current_parent_id: str, uploaded_folder_id: str) -> Dict[str, Any]:
    """
    Move a file to the Uploaded subfolder by swapping parent references.
    """
    return service.files().update(
        fileId=file_id,
        addParents=uploaded_folder_id,
        removeParents=current_parent_id,
        fields="id, parents",
    ).execute()