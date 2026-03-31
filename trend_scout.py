"""
trend_scout.py — Scans competitor channels from the 'Competitor Tracker' sheet,
finds outlier videos, and writes results to the 'Daily Outliers' tab.

Columns: Date, Platform, Channel, Title, Views, Outlier Score, URL, Hook Transcript
"""

import os
import re
import datetime
from dotenv import load_dotenv
from googleapiclient.discovery import build
from sheets_helper import append_rows, read_all, clear_data_rows

load_dotenv()

TAB = "Daily Outliers"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")


def get_youtube():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def load_competitors():
    """Load competitor channels from the Competitor Tracker sheet."""
    records = read_all("Competitor Tracker")
    competitors = []
    for r in records:
        url = r.get("YouTube URL", "")
        channel_name = r.get("Channel", "")
        if not url:
            continue
        competitors.append({"name": channel_name, "url": url})
    return competitors


def extract_channel_identifier(url):
    """Extract @handle or channel ID from a YouTube URL."""
    # Handle formats: youtube.com/@handle, youtube.com/channel/UCXXX
    if "/@" in url:
        match = re.search(r"/@([\w.-]+)", url)
        if match:
            return ("handle", match.group(1))
    if "/channel/" in url:
        match = re.search(r"/channel/([\w-]+)", url)
        if match:
            return ("id", match.group(1))
    # Fallback: try the last path segment
    parts = url.rstrip("/").split("/")
    if parts:
        last = parts[-1]
        if last.startswith("@"):
            return ("handle", last.lstrip("@"))
        if last.startswith("UC"):
            return ("id", last)
    return (None, None)


def resolve_channel(yt, identifier_type, identifier):
    """Resolve to channel ID and uploads playlist. 1 quota unit."""
    if identifier_type == "handle":
        resp = yt.channels().list(
            part="snippet,contentDetails",
            forHandle=identifier,
        ).execute()
    elif identifier_type == "id":
        resp = yt.channels().list(
            part="snippet,contentDetails",
            id=identifier,
        ).execute()
    else:
        return None

    if resp.get("items"):
        item = resp["items"][0]
        return {
            "channel_id": item["id"],
            "channel_name": item["snippet"]["title"],
            "uploads_playlist": item["contentDetails"]["relatedPlaylists"]["uploads"],
        }
    return None


def get_recent_video_ids(yt, uploads_playlist_id, max_results=10):
    """Get recent video IDs from uploads playlist. 1 quota unit."""
    resp = yt.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
    ).execute()
    return [item["contentDetails"]["videoId"] for item in resp.get("items", [])]


def get_video_details(yt, video_ids):
    """Get stats and snippets for videos. 1 quota unit per 50 videos."""
    resp = yt.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids),
    ).execute()
    results = []
    for item in resp.get("items", []):
        results.append({
            "video_id": item["id"],
            "title": item["snippet"]["title"],
            "description": item["snippet"].get("description", ""),
            "views": int(item["statistics"].get("viewCount", 0)),
            "channel": item["snippet"]["channelTitle"],
        })
    return results


def compute_outliers(videos):
    """Score each video relative to the channel's recent average."""
    if not videos:
        return []
    avg_views = sum(v["views"] for v in videos) / len(videos)
    if avg_views == 0:
        return []
    for v in videos:
        v["outlier_score"] = round(v["views"] / avg_views, 1)
    outliers = [v for v in videos if v["outlier_score"] > 1.0]
    outliers.sort(key=lambda v: v["outlier_score"], reverse=True)
    return outliers


def extract_hook(description, max_chars=200):
    """Extract the first meaningful line from the description as a hook proxy."""
    if not description:
        return ""
    lines = [l.strip() for l in description.split("\n") if l.strip()]
    for line in lines:
        if not line.startswith("http") and not line.startswith("#") and len(line) > 15:
            return line[:max_chars]
    return lines[0][:max_chars] if lines else ""


def scout_outliers():
    """Scan competitor channels from the sheet for outlier videos."""
    yt = get_youtube()
    today = datetime.date.today().isoformat()
    all_outliers = []

    competitors = load_competitors()
    print(f"  Loaded {len(competitors)} competitors from Competitor Tracker sheet.\n")

    for comp in competitors:
        name = comp["name"]
        url = comp["url"]
        print(f"  Scanning {name}...")

        id_type, identifier = extract_channel_identifier(url)
        if not id_type:
            print(f"    Could not parse URL: {url}, skipping.")
            continue

        channel = resolve_channel(yt, id_type, identifier)
        if not channel:
            print(f"    Could not resolve {name}, skipping.")
            continue

        try:
            video_ids = get_recent_video_ids(yt, channel["uploads_playlist"], max_results=10)
        except Exception as e:
            print(f"    Error fetching videos: {e}, skipping.")
            continue
        if not video_ids:
            print(f"    No videos found, skipping.")
            continue

        videos = get_video_details(yt, video_ids)
        outliers = compute_outliers(videos)
        print(f"    Found {len(outliers)} outlier(s) from {channel['channel_name']}")

        for o in outliers:
            all_outliers.append({
                "date": today,
                "platform": "YouTube",
                "channel": o["channel"],
                "title": o["title"],
                "views": o["views"],
                "outlier_score": o["outlier_score"],
                "url": f"https://youtube.com/watch?v={o['video_id']}",
                "hook_transcript": extract_hook(o["description"]),
            })

    all_outliers.sort(key=lambda x: x["outlier_score"], reverse=True)
    return all_outliers[:15]


def write_outliers_to_sheet(outliers):
    """Append outlier rows to the Daily Outliers tab."""
    rows = [
        [
            o["date"],
            o["platform"],
            o["channel"],
            o["title"],
            o["views"],
            o["outlier_score"],
            o["url"],
            o["hook_transcript"],
        ]
        for o in outliers
    ]
    count = append_rows(TAB, rows)
    return count


def run():
    print("Clearing previous data from Daily Outliers and Content Calendar...")
    cleared_outliers = clear_data_rows("Daily Outliers")
    cleared_calendar = clear_data_rows("Content Calendar")
    print(f"  Cleared {cleared_outliers} rows from Daily Outliers")
    print(f"  Cleared {cleared_calendar} rows from Content Calendar\n")

    print("Scouting for outliers from Competitor Tracker channels...\n")
    outliers = scout_outliers()
    if not outliers:
        print("No outliers found.")
        return outliers
    print(f"\nFound {len(outliers)} outliers. Writing to '{TAB}' tab...")
    count = write_outliers_to_sheet(outliers)
    print(f"Done — {count} rows written to Google Sheets.")

    print("\nVerifying — last entries from sheet:")
    records = read_all(TAB)
    for r in records[-min(len(outliers), 5):]:
        print(f"  {r.get('Outlier Score',0):>5} | {r.get('Channel','?'):<25} | {r.get('Title','?')}")

    return outliers


if __name__ == "__main__":
    run()
