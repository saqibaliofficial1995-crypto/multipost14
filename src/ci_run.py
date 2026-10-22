"""
Orchestrator pipeline for Channel 14 (Donna Gonzales).
Coordinates Drive sync, normalization, Gemini AI analysis, and YouTube upload.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict

from src.auth import get_google_credentials, get_gemini_key
from src.drive_client import (
    get_drive_service,
    list_drive_files,
    get_or_create_uploaded_folder,
    download_file,
    move_to_uploaded,
)
from src.normalize import get_video_info, normalize_video
from src.llm_meta import generate_video_metadata
from src.yt_client import get_youtube_service, get_channel_info, upload_video


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


def load_uploaded_state() -> Dict[str, Any]:
    state_path = _find_path("state/uploaded.json")
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {"items": {}, "history": []}


def save_uploaded_state(state: Dict[str, Any]) -> None:
    state_path = _find_path("state/uploaded.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def run_pipeline(dry_run: bool = False, max_uploads: int = None) -> None:
    config = load_config()
    folder_id = os.environ.get("DRIVE_FOLDER_ID") or config.get("drive_folder_id")
    if not folder_id:
        raise ValueError("DRIVE_FOLDER_ID not defined in config or env.")

    limit = max_uploads if max_uploads is not None else config.get("max_uploads_per_run", 1)
    privacy_status = config.get("privacy_status", "public")
    made_for_kids = config.get("made_for_kids", False)
    ai_model = config.get("model", "gemini-flash-lite-latest")

    creds = get_google_credentials()
    drive_service = get_drive_service(creds)
    yt_service = get_youtube_service(creds)
    gemini_key = get_gemini_key()

    # Pre-run Channel Audit
    ch_before = get_channel_info(yt_service)
    ch_videos_before = ch_before["video_count"]

    # Pre-run Drive Audit
    video_files_before, non_conforming_before = list_drive_files(drive_service, folder_id)
    drive_videos_before = len(video_files_before)
    uploaded_folder_id = get_or_create_uploaded_folder(drive_service, folder_id)

    print("==================================================")
    print(f"PIPELINE RUN - Channel: {ch_before['title']} ({ch_before['id']})")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPLOAD'}")
    print(f"Drive Videos Pending: {drive_videos_before}")
    print(f"Drive Non-conforming Files: {len(non_conforming_before)}")
    print(f"Channel Video Count Before: {ch_videos_before}")
    print("==================================================")

    state = load_uploaded_state()
    uploaded_items = state.get("items", {})

    pending_videos = [v for v in video_files_before if v["id"] not in uploaded_items]
    if not pending_videos:
        print("[pipeline] No new pending videos found in Drive. All files up to date.")
        return

    to_process = pending_videos[:limit]
    print(f"[pipeline] Selected {len(to_process)} video(s) to process (limit: {limit}).")

    successful_uploads = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for idx, video_meta in enumerate(to_process, 1):
            file_id = video_meta["id"]
            file_name = video_meta["name"]
            raw_file_path = str(tmp_path / f"raw_{file_id}_{file_name}")
            norm_file_path = str(tmp_path / f"norm_{file_id}_{file_name}")

            print(f"\n[{idx}/{len(to_process)}] Downloading file: {file_name} (ID: {file_id})...")
            download_file(drive_service, file_id, raw_file_path)

            print(f"[{idx}/{len(to_process)}] Probing video characteristics...")
            info = get_video_info(raw_file_path)
            duration = info.get("duration", 60.0)

            print(f"[{idx}/{len(to_process)}] Normalizing video to 1080x1920 30fps...")
            processed_video_path = normalize_video(raw_file_path, norm_file_path)

            print(f"[{idx}/{len(to_process)}] Analyzing video content with Gemini Files API...")
            meta = generate_video_metadata(
                video_path=processed_video_path,
                api_key=gemini_key,
                model=ai_model,
                duration=duration,
            )

            print("\n----- METADATA SUMMARY -----")
            print(f"Title: {meta['title']} ({len(meta['title'])} chars)")
            print(f"Topic: {meta['topic']}")
            print(f"Tags Count: {len(meta['tags'])}")
            print(f"Tags Total Chars: {len(','.join(meta['tags']))}")
            print(f"Hashtags: {' '.join(meta['hashtags'])}")
            print(f"Description:\n{meta['description']}")
            print("----------------------------\n")

            if dry_run:
                print(f"[dry-run] Video simulation complete for {file_name}. Dry-run stops before upload.")
                continue

            print(f"[{idx}/{len(to_process)}] Uploading video to YouTube...")
            upload_res = upload_video(
                service=yt_service,
                file_path=processed_video_path,
                metadata=meta,
                privacy_status=privacy_status,
                made_for_kids=made_for_kids,
            )
            video_id = upload_res.get("id")

            print(f"[{idx}/{len(to_process)}] Moving Drive file to Uploaded folder...")
            move_to_uploaded(drive_service, file_id, folder_id, uploaded_folder_id)

            now_iso = datetime.now(timezone.utc).isoformat()
            state.setdefault("items", {})[file_id] = {
                "file_name": file_name,
                "video_id": video_id,
                "title": meta["title"],
                "topic": meta["topic"],
                "tags": meta["tags"],
                "hashtags": meta["hashtags"],
                "uploaded_at": now_iso,
            }
            state.setdefault("history", []).append({
                "file_id": file_id,
                "video_id": video_id,
                "title": meta["title"],
                "topic": meta["topic"],
                "timestamp": now_iso,
            })
            save_uploaded_state(state)

            successful_uploads.append({
                "file_id": file_id,
                "video_id": video_id,
                "title": meta["title"],
                "topic": meta["topic"],
                "url": f"https://youtu.be/{video_id}",
            })

    # Post-run Audits
    video_files_after, _ = list_drive_files(drive_service, folder_id)
    drive_videos_after = len(video_files_after)
    ch_after = get_channel_info(yt_service)
    ch_videos_after = ch_after["video_count"]

    print("\n==================================================")
    print("RUN COMPLETION REPORT")
    print(f"Drive Video Count: {drive_videos_before} -> {drive_videos_after}")
    print(f"Channel Video Count: {ch_videos_before} -> {ch_videos_after}")
    if successful_uploads:
        print(f"Uploaded {len(successful_uploads)} video(s):")
        for up in successful_uploads:
            print(f"  - {up['title']} | ID: {up['video_id']} | Topic: {up['topic']} | URL: {up['url']}")
    print("==================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Channel 14 Orchestrator Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Simulate run without uploading")
    parser.add_argument("--max-uploads", type=int, default=None, help="Maximum videos to process")
    args = parser.parse_args()
    run_pipeline(dry_run=args.dry_run, max_uploads=args.max_uploads)