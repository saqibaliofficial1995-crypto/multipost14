"""
YouTube Analytics v2 weekly report puller for Channel 14.
Retrieves views, estimatedMinutesWatched, averageViewDuration, subscribersGained, subscribersLost.
"""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from typing import Any, Dict
from googleapiclient.discovery import build

from src.auth import get_google_credentials


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


def get_analytics_service(credentials):
    """Build YouTube Analytics v2 service."""
    return build("youtubeAnalytics", "v2", credentials=credentials)


def pull_weekly_analytics() -> Dict[str, Any]:
    creds = get_google_credentials()
    service = get_analytics_service(creds)

    today = datetime.now(timezone.utc).date()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=6)

    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    print(f"[analytics] Pulling YouTube Analytics from {start_str} to {end_str}...")

    response = service.reports().query(
        ids="channel==MINE",
        startDate=start_str,
        endDate=end_str,
        metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
    ).execute()

    reports_dir = _find_path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"analytics_{today.isoformat()}.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(response, f, indent=2, ensure_ascii=False)

    print(f"[analytics] Saved weekly analytics report to {report_file}")
    return response


if __name__ == "__main__":
    pull_weekly_analytics()