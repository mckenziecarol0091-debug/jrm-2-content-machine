"""
trend_scout.py — Scans competitor channels from the 'Competitor Tracker' sheet,
finds two types of videos and writes results to the 'Daily Outliers' tab:

  1. OUTLIER  — videos scoring ≥2x the channel's recent average views
  2. BRAND MATCH — videos that align with the Brand Voice even if not outliers

Columns: Date, Platform, Channel, Title, Views, Outlier Score, Brand Score, Type, URL, Hook Transcript
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

# ── Brand-match scoring ────────────────────────────────────────────
#
# 4 Content Pillars:
#   1. AI Tools & Automation
#   2. How to Make Money with AI
#   3. Real Estate + AI
#   4. Go High Level (GHL)
#
# Keyword lists are supplemented at runtime from the Brand Voice sheet.

# Jake's actual tool stack — videos about these get a big scoring boost
MY_TOOLS = [
    "go high level", "gohighlevel", "highlevel", "ghl", "high level",
    "claude", "claude code", "claude ai", "anthropic",
    "higgsfield", "higgsfield ai",
    "gemini", "google gemini",
    "notebooklm", "notebook lm",
    "chatgpt", "chat gpt", "openai",
    "lovable", "lovable.dev",
]

PILLAR_KEYWORDS = {
    # Pillar 1: AI Tools & Automation
    "ai_tools": [
        "ai", "artificial intelligence", "automation", "automate", "workflow",
        "system", "systems", "operator", "operations", "chatgpt", "claude",
        "gpt", "llm", "agent", "ai agent", "no-code", "low-code", "saas",
        "software", "prompt", "deploy", "scale", "efficiency", "productivity",
        "ai tool", "ai tools", "zapier", "make.com", "n8n", "api",
    ],
    # Pillar 2: How to Make Money with AI
    "ai_money": [
        "make money", "income", "revenue", "profit", "monetize", "side hustle",
        "ai business", "business model", "case study", "client", "freelance",
        "agency", "smma", "saas", "recurring revenue", "passive income",
        "operator", "ai operator", "charge", "pricing", "sell",
        "entrepreneur", "entrepreneurship", "founder", "startup",
    ],
    # Pillar 3: Real Estate + AI
    "real_estate": [
        "real estate", "realtor", "real estate agent", "listing", "listings",
        "buyer", "seller", "lead generation", "leads", "lead gen", "open house",
        "mortgage", "property", "home", "homes", "mls", "crm", "follow up",
        "follow-up", "client follow", "market analysis", "sales funnel",
        "real estate funnel", "real estate ai", "cold calling", "door knocking",
        "isa", "inside sales", "expired listing", "fsbo", "zillow", "realtor.com",
        "keller williams", "exp realty", "compass", "brokerage",
    ],
    # Pillar 4: Go High Level (GHL)
    "ghl": [
        "go high level", "gohighlevel", "highlevel", "ghl", "high level",
        "crm", "sub-account", "sub account", "subaccount", "snapshot",
        "funnel", "funnels", "landing page", "landing pages", "webinar funnel",
        "sms", "email sequence", "drip campaign", "pipeline", "automation",
        "booking", "calendar", "reputation management", "review", "reviews",
        "white label", "whitelabel", "saas mode", "agency", "click funnels",
        "clickfunnels", "kartra", "hubspot",
    ],
}

AUDIENCE_KEYWORDS = [
    "entrepreneur", "business owner", "founder", "operator", "ceo",
    "freelancer", "agency", "agency owner", "small business", "solopreneur",
    "creator", "real estate agent", "realtor", "broker", "ghl user",
    "highlevel user",
]

VOICE_KEYWORDS = [
    "how to", "how i", "i built", "i used", "here's how", "step by step",
    "the truth", "no one talks about", "stop doing", "why you",
    "what i learned", "real talk", "let me show", "tutorial",
    "beginner", "guide", "walkthrough",
]


def load_brand_voice():
    """Load Brand Voice key-value pairs from the sheet."""
    records = read_all("Brand Voice")
    voice = {}
    for r in records:
        voice[r.get("Key", "")] = r.get("Value", "")
    return voice


def _extra_keywords_from_voice(brand_voice):
    """Pull additional keywords from Brand Voice sheet values."""
    extra = []
    for key in ("Topics", "Words You Use", "Hooks That Work"):
        val = brand_voice.get(key, "")
        if val:
            extra.extend([w.strip().lower() for w in re.split(r"[,;\n]", val) if len(w.strip()) > 2])
    return extra


def score_brand_match(video, brand_voice, extra_kw):
    """Score a video 0-10 for brand relevance across all 4 pillars.

    Videos about tools Jake actually uses get a big boost (+3).
    A video only needs to match ONE pillar well to qualify.  The best
    pillar score is used so real-estate or GHL videos aren't penalised
    for missing AI keywords and vice-versa.
    """
    text = (video["title"] + " " + video.get("description", "")).lower()

    # Check if the video is about a tool Jake actually uses
    my_tool_hits = sum(1 for kw in MY_TOOLS if kw in text)
    tool_boost = min(my_tool_hits * 1.5, 3)  # up to +3 bonus

    # Score each pillar independently, take the best
    best_pillar_hits = 0
    for kw_list in PILLAR_KEYWORDS.values():
        hits = sum(1 for kw in kw_list if kw in text)
        best_pillar_hits = max(best_pillar_hits, hits)

    # Also check extra keywords from Brand Voice sheet
    extra_hits = sum(1 for kw in extra_kw if kw in text)
    best_pillar_hits += extra_hits

    audience_hits = sum(1 for kw in AUDIENCE_KEYWORDS if kw in text)
    voice_hits = sum(1 for kw in VOICE_KEYWORDS if kw in text)

    # Weighted score out of 10: pillar (4) + tool boost (3) + audience (1.5) + voice (1.5)
    score = (
        min(best_pillar_hits * 1.0, 4)
        + tool_boost
        + min(audience_hits * 1.0, 1.5)
        + min(voice_hits * 1.0, 1.5)
    )
    return round(score, 1)


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


def score_videos(videos):
    """Compute outlier_score for every video relative to channel average."""
    if not videos:
        return []
    avg_views = sum(v["views"] for v in videos) / len(videos)
    if avg_views == 0:
        return []
    for v in videos:
        v["outlier_score"] = round(v["views"] / avg_views, 1)
    return videos


def extract_hook(description, max_chars=200):
    """Extract the first meaningful line from the description as a hook proxy."""
    if not description:
        return ""
    lines = [l.strip() for l in description.split("\n") if l.strip()]
    for line in lines:
        if not line.startswith("http") and not line.startswith("#") and len(line) > 15:
            return line[:max_chars]
    return lines[0][:max_chars] if lines else ""


OUTLIER_THRESHOLD = 2.0   # ≥2x channel average = outlier
BRAND_MATCH_MIN = 3.0     # minimum brand score to qualify as brand match


def scout_all(brand_voice):
    """Scan competitor channels for Outlier and Brand Match videos."""
    yt = get_youtube()
    today = datetime.date.today().isoformat()
    extra_kw = _extra_keywords_from_voice(brand_voice)

    outlier_results = []
    brand_results = []

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
        videos = score_videos(videos)

        n_outliers = 0
        n_brand = 0
        for v in videos:
            brand_score = score_brand_match(v, brand_voice, extra_kw)
            v["brand_score"] = brand_score
            is_outlier = v["outlier_score"] >= OUTLIER_THRESHOLD

            row = {
                "date": today,
                "platform": "YouTube",
                "channel": v["channel"],
                "title": v["title"],
                "views": v["views"],
                "outlier_score": v["outlier_score"],
                "brand_score": brand_score,
                "url": f"https://youtube.com/watch?v={v['video_id']}",
                "hook_transcript": extract_hook(v.get("description", "")),
            }

            if is_outlier:
                row["type"] = "Outlier"
                outlier_results.append(row)
                n_outliers += 1
            elif brand_score >= BRAND_MATCH_MIN:
                row["type"] = "Brand Match"
                brand_results.append(row)
                n_brand += 1

        print(f"    {channel['channel_name']}: {n_outliers} outlier(s), {n_brand} brand match(es)")

    # Sort each group by its primary metric
    outlier_results.sort(key=lambda x: x["outlier_score"], reverse=True)
    brand_results.sort(key=lambda x: x["brand_score"], reverse=True)

    # Keep top results from each group
    outlier_results = outlier_results[:10]
    brand_results = brand_results[:10]

    combined = outlier_results + brand_results
    print(f"\n  Totals: {len(outlier_results)} outliers, {len(brand_results)} brand matches")
    return combined


def write_to_sheet(results):
    """Append result rows to the Daily Outliers tab."""
    rows = [
        [
            r["date"],
            r["platform"],
            r["channel"],
            r["title"],
            r["views"],
            r["outlier_score"],
            r["brand_score"],
            r["type"],
            r["url"],
            r["hook_transcript"],
        ]
        for r in results
    ]
    count = append_rows(TAB, rows)
    return count


def run():
    print("Clearing previous data from Daily Outliers, Content Calendar, and Brand Match Ideas...")
    cleared_outliers = clear_data_rows("Daily Outliers")
    cleared_calendar = clear_data_rows("Content Calendar")
    cleared_brand = clear_data_rows("Brand Match Ideas")
    print(f"  Cleared {cleared_outliers} rows from Daily Outliers")
    print(f"  Cleared {cleared_calendar} rows from Content Calendar")
    print(f"  Cleared {cleared_brand} rows from Brand Match Ideas\n")

    print("Loading Brand Voice for brand-match scoring...")
    brand_voice = load_brand_voice()
    print(f"  Loaded {len(brand_voice)} brand voice keys: {', '.join(brand_voice.keys())}\n")

    print("Scouting competitor channels for Outliers + Brand Matches...\n")
    results = scout_all(brand_voice)
    if not results:
        print("No results found.")
        return results
    print(f"\nWriting {len(results)} results to '{TAB}' tab...")
    count = write_to_sheet(results)
    print(f"Done — {count} rows written to Google Sheets.")

    print("\nVerifying — last entries from sheet:")
    records = read_all(TAB)
    for r in records[-min(len(results), 5):]:
        print(f"  [{r.get('Type','?'):>12}] {r.get('Outlier Score',''):>4}x | B:{r.get('Brand Score',''):>4} | {r.get('Channel','?'):<25} | {r.get('Title','?')}")

    return results


if __name__ == "__main__":
    run()
