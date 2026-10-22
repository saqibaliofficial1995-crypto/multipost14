"""
Automated AI Comment Reply module for Channel 14 (Donna Gonzales).
Listens for comments across channel videos and generates warm, natural context-aware responses.
"""

import argparse
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List
import requests

from src.auth import get_google_credentials, get_gemini_key
from src.yt_client import get_youtube_service, get_channel_info

SPAM_KEYWORDS = ["telegram", "whatsapp", "crypto", "bitcoin", "invest", "forex", "cash", "dm me", "inbox me", "promo", "follow back", "free money", "http", "www.", ".com"]
EMOJI_PATTERN = re.compile(r"^[\s\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff]+$")


def _find_path(rel_path: str) -> Path:
    candidates = [
        Path.cwd() / rel_path,
        Path(__file__).resolve().parent.parent / rel_path,
        Path(__file__).resolve().parent.parent.parent / rel_path,
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path.cwd() / rel_path


def load_config() -> Dict[str, Any]:
    cfg_path = _find_path("config.json")
    with open(cfg_path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_replied_state() -> Dict[str, Any]:
    state_path = _find_path("state/replied.json")
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {"replied": [], "history": []}


def save_replied_state(state: Dict[str, Any]) -> None:
    state_path = _find_path("state/replied.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def is_eligible_comment(comment_text: str, thread_id: str, replied_ids: set, channel_id: str, replies_list: list) -> bool:
    if thread_id in replied_ids:
        return False

    text = comment_text.strip()
    if len(text) < 3:
        return False

    # Pure emoji check
    if EMOJI_PATTERN.match(text):
        return False

    lower_text = text.lower()
    for kw in SPAM_KEYWORDS:
        if kw in lower_text:
            return False

    # Check if channel already replied
    for reply in replies_list:
        rep_author_id = (
            reply.get("snippet", {})
            .get("authorChannelId", {})
            .get("value")
        )
        if rep_author_id == channel_id:
            return False

    return True


def generate_comment_reply(comment_text: str, video_title: str, api_key: str, model: str = "gemini-flash-lite-latest") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    prompt = (
        "You are Donna Gonzales responding warmly and authentically to a viewer comment on your YouTube video.\n"
        f"Video Context: {video_title}\n"
        f"Viewer Comment: \"{comment_text}\"\n\n"
        "Instructions:\n"
        "- Provide exactly ONE natural reply.\n"
        "- 1 to 2 short sentences.\n"
        "- Friendly, thoughtful, authentic.\n"
        "- NO links, NO asking for likes/subscribes, NO sales pitch.\n"
        "- Maximum 1 emoji.\n"
        "- Never use canned or repetitive phrases.\n"
        "- Respond in the same language as the viewer comment.\n"
        "Output ONLY the plain reply text with no quotation marks."
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}]
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        reply_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        reply_text = reply_text.strip('"\'')
        return reply_text
    except Exception as e:
        print(f"[reply] Gemini generation failed: {e}. Using gentle fallback.")
        return "Thank you so much for watching and sharing your thoughts!"


def process_comments(dry_run: bool = False) -> None:
    config = load_config()
    reply_cfg = config.get("comment_reply", {})
    if not reply_cfg.get("enabled", True):
        print("[reply] Comment reply module is disabled in config.json.")
        return

    max_replies = reply_cfg.get("max_replies_per_run", 15)
    lookback_days = reply_cfg.get("lookback_days", 7)

    creds = get_google_credentials()
    service = get_youtube_service(creds)
    ch_info = get_channel_info(service)
    channel_id = ch_info["id"]

    state = load_replied_state()
    replied_ids = set(state.get("replied", []))

    api_key = get_gemini_key()
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    print(f"[reply] Scanning comment threads for channel {ch_info['title']} ({channel_id}) past {lookback_days} days...")

    page_token = None
    eligible_threads: List[Dict[str, Any]] = []

    while True:
        try:
            req = service.commentThreads().list(
                part="snippet,replies",
                allThreadsRelatedToChannelId=channel_id,
                order="time",
                maxResults=100,
                pageToken=page_token,
            )
            res = req.execute()
        except Exception as e:
            print(f"[reply] Error fetching comment threads: {e}")
            break

        items = res.get("items", [])
        if not items:
            break

        reached_cutoff = False
        for item in items:
            snippet = item.get("snippet", {})
            top_level = snippet.get("topLevelComment", {}).get("snippet", {})
            thread_id = item.get("id")
            pub_str = top_level.get("publishedAt", "")

            try:
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub_dt < cutoff_date:
                    reached_cutoff = True
                    break
            except Exception:
                pass

            comment_text = top_level.get("textOriginal", "")
            video_id = snippet.get("videoId", "")
            replies_list = item.get("replies", {}).get("comments", [])

            if is_eligible_comment(comment_text, thread_id, replied_ids, channel_id, replies_list):
                eligible_threads.append({
                    "thread_id": thread_id,
                    "video_id": video_id,
                    "comment_text": comment_text,
                    "author": top_level.get("authorDisplayName", "Viewer"),
                })

        if reached_cutoff or not res.get("nextPageToken"):
            break
        page_token = res.get("nextPageToken")

    if not eligible_threads:
        print("[reply] No eligible comments found requiring reply. PASS.")
        return

    print(f"[reply] Found {len(eligible_threads)} eligible comment(s). Processing up to {max_replies}...")
    processed_count = 0

    for item in eligible_threads[:max_replies]:
        thread_id = item["thread_id"]
        video_id = item["video_id"]
        comment_text = item["comment_text"]

        # Fetch video title if video_id is present
        video_title = "Modern Lifestyle and Design Video"
        if video_id:
            try:
                v_res = service.videos().list(part="snippet", id=video_id).execute()
                v_items = v_res.get("items", [])
                if v_items:
                    video_title = v_items[0].get("snippet", {}).get("title", video_title)
            except Exception:
                pass

        reply_text = generate_comment_reply(comment_text, video_title, api_key, model=config.get("model", "gemini-flash-lite-latest"))
        print(f"[reply] {video_id} {thread_id} -> \"{reply_text}\"")

        if not dry_run:
            try:
                service.comments().insert(
                    part="snippet",
                    body={"snippet": {"parentId": thread_id, "textOriginal": reply_text}},
                ).execute()

                state["replied"].append(thread_id)
                state.setdefault("history", []).append({
                    "thread_id": thread_id,
                    "video_id": video_id,
                    "reply": reply_text,
                    "replied_at": datetime.now(timezone.utc).isoformat(),
                })
                processed_count += 1
            except Exception as e:
                print(f"[reply] Failed to post comment reply: {e}")
        else:
            processed_count += 1

    if not dry_run and processed_count > 0:
        save_replied_state(state)
        print(f"[reply] Successfully posted and recorded {processed_count} replies.")
    else:
        print(f"[reply] Dry-run complete. Planned {processed_count} replies.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Channel 14 Comment Reply Module")
    parser.add_argument("--dry-run", action="store_true", help="Simulate replies without posting")
    args = parser.parse_args()
    process_comments(dry_run=args.dry_run)