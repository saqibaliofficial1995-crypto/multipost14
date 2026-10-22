"""
Video normalization module using ffprobe and ffmpeg.
Converts videos to standard 1080x1920 30fps vertical format with graceful copy fallback.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any


def get_video_info(video_path: str) -> Dict[str, Any]:
    """
    Extract duration, width, height, and format information via ffprobe.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration:stream=width,height,duration,r_frame_rate,codec_name",
        "-of", "json",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        duration = 0.0
        if "format" in data and "duration" in data["format"]:
            duration = float(data["format"]["duration"])
        elif "streams" in data and data["streams"]:
            for stream in data["streams"]:
                if "duration" in stream:
                    duration = float(stream["duration"])
                    break
        width = 0
        height = 0
        if "streams" in data:
            for stream in data["streams"]:
                if "width" in stream and "height" in stream:
                    width = int(stream["width"])
                    height = int(stream["height"])
                    break
        return {"duration": duration, "width": width, "height": height, "raw": data}
    except Exception as e:
        print(f"[normalize] ffprobe warning: {e}")
        return {"duration": 0.0, "width": 0, "height": 0, "raw": {}}


def normalize_video(input_path: str, output_path: str) -> str:
    """
    Normalize video to 1080x1920, 30 fps, H.264 + AAC.
    Falls back gracefully to copying the file if ffmpeg is unavailable or fails.
    """
    input_file = Path(input_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    filter_complex = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_file),
        "-vf", filter_complex,
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",
        str(output_file),
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        if output_file.exists() and output_file.stat().st_size > 0:
            return str(output_file)
    except Exception as e:
        print(f"[normalize] ffmpeg failed: {e}. Falling back to copy.")

    # Fallback to copy
    shutil.copy2(input_path, output_path)
    return str(output_path)