"""
Authentication module for YouTube Channel 14 (Donna Gonzales).
Handles Google OAuth credentials and Gemini API key resolution.
"""

import json
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/drive",
]


def _find_path(relative_path: str) -> Optional[Path]:
    """Search common base directories for a relative path."""
    candidates = [
        Path.cwd() / relative_path,
        Path(__file__).resolve().parent.parent / relative_path,
        Path(__file__).resolve().parent.parent.parent / relative_path,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def get_google_credentials() -> Credentials:
    """
    Obtain Google OAuth credentials with priority:
    1. Environment variables (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN)
    2. Local tokens/token.json file
    3. Interactive InstalledAppFlow using tokens/client_secret.json
    """
    client_id = os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("YT_CLIENT_SECRET")
    refresh_token = os.environ.get("YT_REFRESH_TOKEN")

    if client_id and client_secret and refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        if not creds.valid or creds.expired:
            creds.refresh(Request())
        return creds

    token_path = _find_path("tokens/token.json")
    if token_path and token_path.exists():
        with open(token_path, "r", encoding="utf-8-sig") as f:
            token_data = json.load(f)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        if creds and creds.valid:
            return creds

    client_secret_path = _find_path("tokens/client_secret.json")
    if not client_secret_path:
        # Fallback to default expected location in parent dir
        client_secret_path = Path(__file__).resolve().parent.parent.parent / "tokens" / "client_secret.json"

    if not client_secret_path.exists():
        raise FileNotFoundError(f"client_secret.json not found at {client_secret_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)

    save_dir = client_secret_path.parent
    save_dir.mkdir(parents=True, exist_ok=True)
    save_token_path = save_dir / "token.json"
    with open(save_token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    return creds


def get_gemini_key() -> str:
    """
    Retrieve Gemini API key from GEMINI_API_KEY env or tokens/gemini_key.txt.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()

    key_file = _find_path("tokens/gemini_key.txt")
    if not key_file:
        key_file = Path(__file__).resolve().parent.parent.parent / "tokens" / "gemini_key.txt"

    if key_file.exists():
        with open(key_file, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()
            if content:
                return content

    raise ValueError("Gemini API key not found in GEMINI_API_KEY env or tokens/gemini_key.txt")