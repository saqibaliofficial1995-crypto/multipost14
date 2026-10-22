"""
Gemini Files API client and metadata generator for Channel 14.
Watches video content to derive title, description, tags, hashtags, and topic.
"""

import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

CURRENCY_PATTERN = re.compile(r'[\$\€\£\¥\₹]|\b(USD|AED|EUR|GBP|INR|PKR)\b', re.IGNORECASE)
MAGNITUDE_PATTERN = re.compile(r'\b\d+([.,]\d+)?\s*(m|b|k|million|billion|sqft|sq\s*ft|feet)\b', re.IGNORECASE)


def upload_to_gemini_files(file_path: str, api_key: str) -> Dict[str, Any]:
    """
    Upload video file to Gemini Files API using resumable protocol and poll until ACTIVE.
    """
    file_obj = Path(file_path)
    file_size = file_obj.stat().st_size
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "video/mp4"

    start_url = f"https://generativelanguage.googleapis.com/upload/v1beta/files?key={api_key}"
    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(file_size),
        "X-Goog-Upload-Header-Content-Type": mime_type,
        "Content-Type": "application/json",
    }
    body = json.dumps({"file": {"display_name": file_obj.name}})
    init_res = requests.post(start_url, headers=headers, data=body, timeout=30)
    init_res.raise_for_status()

    upload_url = init_res.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        raise RuntimeError("Failed to retrieve X-Goog-Upload-URL from Gemini Files API")

    upload_headers = {
        "Content-Length": str(file_size),
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
    }
    with open(file_path, "rb") as f:
        upload_res = requests.post(upload_url, headers=upload_headers, data=f, timeout=120)
    upload_res.raise_for_status()

    file_info = upload_res.json().get("file", {})
    file_name = file_info.get("name")
    if not file_name:
        raise RuntimeError(f"Upload completed but no file name returned: {upload_res.text}")

    print(f"[meta] Uploaded file to Gemini Files API: {file_name}. Waiting for ACTIVE state...")
    poll_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"
    for _ in range(60):
        poll_res = requests.get(poll_url, timeout=20)
        poll_res.raise_for_status()
        state = poll_res.json().get("state")
        if state == "ACTIVE":
            return poll_res.json()
        elif state == "FAILED":
            raise RuntimeError(f"Gemini Files processing failed for {file_name}: {poll_res.text}")
        time.sleep(5)

    raise TimeoutError(f"Timeout waiting for Gemini File {file_name} to become ACTIVE")


def delete_gemini_file(file_name: str, api_key: str) -> None:
    """Clean up uploaded file from Gemini Files API."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}?key={api_key}"
        requests.delete(url, timeout=15)
    except Exception as e:
        print(f"[meta] Notice: Failed to delete Gemini file {file_name}: {e}")


def _strip_disallowed_patterns(text: str) -> str:
    """Remove currency and magnitude expressions."""
    cleaned = CURRENCY_PATTERN.sub("", text)
    cleaned = MAGNITUDE_PATTERN.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def sanitize_and_validate(raw_meta: Dict[str, Any], duration: float) -> Dict[str, Any]:
    """
    Sanitizes, validates, and standardizes video metadata according to Channel 14 rules.
    """
    raw_title = raw_meta.get("title", "")
    title = _strip_disallowed_patterns(raw_title)
    if not title:
        title = "Incredible Living & Modern Lifestyle Experience"
    if len(title) >= 60:
        title = title[:56].rsplit(" ", 1)[0].strip()

    raw_body = raw_meta.get("description", "")
    body = _strip_disallowed_patterns(raw_body)
    if not body:
        body = "Explore this inspiring showcase of architecture, lifestyle, and captivating living spaces."

    raw_tags = raw_meta.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

    clean_tags: List[str] = []
    seen = set()
    for t in raw_tags:
        cleaned = _strip_disallowed_patterns(str(t)).strip("# ")
        if cleaned and len(cleaned) > 2 and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            clean_tags.append(cleaned)

    fallback_tags = [
        "luxury design", "interior decor", "modern architecture",
        "home makeover", "house tour", "dream home", "lifestyle inspiration",
        "aesthetic living", "room styling", "interior styling", "creative spaces",
        "architectural digest", "home tour"
    ]
    for ft in fallback_tags:
        if len(clean_tags) >= 12:
            break
        if ft.lower() not in seen:
            seen.add(ft.lower())
            clean_tags.append(ft)

    clean_tags = clean_tags[:15]
    while len(",".join(clean_tags)) >= 460 and len(clean_tags) > 10:
        clean_tags.pop()

    raw_hashtags = raw_meta.get("hashtags", [])
    if isinstance(raw_hashtags, str):
        raw_hashtags = [h.strip() for h in raw_hashtags.split() if h.strip()]

    formatted_hashtags: List[str] = []
    for h in raw_hashtags:
        h_str = str(h).strip()
        if not h_str.startswith("#"):
            h_str = f"#{h_str}"
        h_clean = _strip_disallowed_patterns(h_str)
        if h_clean and h_clean != "#" and h_clean.lower() not in [x.lower() for x in formatted_hashtags]:
            formatted_hashtags.append(h_clean)

    is_short = duration <= 60.0
    if is_short and "#shorts" not in [x.lower() for x in formatted_hashtags]:
        formatted_hashtags.insert(0, "#shorts")

    default_hashtags = ["#shorts", "#homedesign", "#luxuryhomes"] if is_short else ["#homedesign", "#luxuryhomes", "#architecture"]
    for dh in default_hashtags:
        if len(formatted_hashtags) >= 3:
            break
        if dh.lower() not in [x.lower() for x in formatted_hashtags]:
            formatted_hashtags.append(dh)

    formatted_hashtags = formatted_hashtags[:3]

    hashtags_line = " ".join(formatted_hashtags)
    final_description = f"{body}\n\n{hashtags_line}\n\nDonna Gonzales"

    topic = str(raw_meta.get("topic", "")).strip()
    topic = _strip_disallowed_patterns(topic)

    return {
        "title": title,
        "description": final_description,
        "body": body,
        "tags": clean_tags,
        "hashtags": formatted_hashtags,
        "topic": topic,
        "path": "video_ai_gemini",
    }


def generate_video_metadata(video_path: str, api_key: str, model: str = "gemini-flash-lite-latest", duration: float = 60.0) -> Dict[str, Any]:
    """
    Generate YouTube metadata by watching the video via Gemini Files API.
    Mandatory topic requirement with retry logic and fallback logging.
    """
    file_info = upload_to_gemini_files(video_path, api_key)
    file_uri = file_info.get("uri")
    file_name = file_info.get("name")
    mime_type = file_info.get("mimeType", "video/mp4")

    prompt = (
        "You are an expert YouTube metadata specialist for the Donna Gonzales channel.\n"
        "Watch this video carefully and generate engaging, accurate metadata based strictly on what is seen in the video.\n"
        "Output ONLY valid JSON with keys: title, description, tags, hashtags, topic.\n"
        "- title: engaging YouTube title under 60 characters (no currency, no price, no million/sqft claims)\n"
        "- description: 2-3 sentences describing the video content\n"
        "- tags: list of 10 to 14 relevant search tags\n"
        "- hashtags: list of exactly 3 relevant hashtags (include #shorts if video is under 60 seconds)\n"
        "- topic: MANDATORY concise niche/subject of the video (e.g., 'Modern Architecture', 'Luxury Home Interior', 'Cozy Living Space')\n"
        "Do NOT include any currency symbols ($ , € , £ , ¥ , ₹ , USD , AED , EUR) or magnitude numbers (million, billion, sqft, m, k).\n"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"file_data": {"file_uri": file_uri, "mime_type": mime_type}},
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=90)
        res.raise_for_status()
        data = res.json()
        text_response = data["candidates"][0]["content"]["parts"][0]["text"]
        raw_meta = json.loads(text_response)

        # Mandatory topic check: if missing or empty, retry ONCE with reminder
        topic_val = str(raw_meta.get("topic", "")).strip()
        if not topic_val:
            print("[meta] Warning: Model returned empty topic. Retrying with explicit reminder...")
            retry_prompt = prompt + "\nCRITICAL: The 'topic' field was missing previously. You MUST supply a non-empty 'topic' string identifying the video subject."
            payload["contents"][0]["parts"][1]["text"] = retry_prompt
            retry_res = requests.post(url, headers=headers, json=payload, timeout=90)
            if retry_res.status_code == 200:
                retry_data = retry_res.json()
                retry_text = retry_data["candidates"][0]["content"]["parts"][0]["text"]
                retry_meta = json.loads(retry_text)
                raw_meta["topic"] = retry_meta.get("topic", "")

        # Check topic again
        topic_val = str(raw_meta.get("topic", "")).strip()
        if not topic_val:
            raw_meta["topic"] = "Modern Living & Architecture"
            print("[meta] topic fallback used")

        validated = sanitize_and_validate(raw_meta, duration)
        return validated

    finally:
        delete_gemini_file(file_name, api_key)