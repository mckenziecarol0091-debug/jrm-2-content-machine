"""
trend_scout.py — Scans competitor channels from the 'Competitor Tracker' sheet,
finds two types of videos and writes results to the 'Daily Outliers' tab:

  1. OUTLIER  — videos scoring ≥2x the channel's recent average views
  2. BRAND MATCH — videos that align with the Brand Voice even if not outliers

Results are balanced across the 4 content pillars (top 5 each = 20 total).

Columns: Date, Pillar, Platform, Channel, Title, Views, Outlier Score, Brand Score, Type, URL, Hook Transcript
"""

import os
import re
import datetime
from dotenv import load_dotenv
from googleapiclient.discovery import build
from sheets_helper import append_rows, read_all, delete_old_rows, get_existing_values

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
        # Real estate lead gen & CRM
        "sphere of influence", "soi", "database", "nurture", "drip",
        "text blast", "speed to lead", "internet leads", "online leads",
        "circle prospecting", "just listed", "just sold", "farming",
        "geographic farming", "buyer leads", "seller leads", "listing leads",
        "real estate crm", "kvcore", "follow up boss", "followupboss",
        "sierra interactive", "boomtown", "chime", "lofty", "cinc",
        "real estate webinar", "real estate funnel", "idx", "home valuation",
        "seller funnel", "buyer funnel", "real estate ads", "google ads realtor",
        "facebook ads real estate", "instagram real estate", "real estate marketing",
        # AI for realtors
        "ai for realtors", "ai real estate", "chatgpt real estate",
        "ai listing description", "ai follow up", "ai for agents",
        "ai prospecting", "virtual assistant real estate",
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
        # GHL for real estate
        "ghl real estate", "highlevel real estate", "ghl realtor",
        "ghl funnel", "ghl automation", "ghl workflow", "ghl snapshot",
        "ghl landing page", "ghl sms", "ghl email", "ghl pipeline",
        "ghl for agents", "ghl lead gen", "ghl webinar",
        "missed call text back", "ghl review", "ghl reputation",
        "conversation ai", "ghl bot", "ghl ai",
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


PILLAR_NAMES = {
    "ai_tools": "AI Tools & Automation",
    "ai_money": "How to Make Money with AI",
    "real_estate": "Real Estate + AI",
    "ghl": "Go High Level",
}

# Ordered list for consistent pillar sorting in output
PILLAR_ORDER = ["AI Tools & Automation", "How to Make Money with AI",
                "Real Estate + AI", "Go High Level"]


def detect_pillar(video):
    """Detect the best-matching content pillar for a video."""
    text = (video["title"] + " " + video.get("description", "")).lower()
    best_key = "ai_tools"
    best_hits = 0
    for key, kw_list in PILLAR_KEYWORDS.items():
        hits = sum(1 for kw in kw_list if kw in text)
        if hits > best_hits:
            best_hits = hits
            best_key = key
    return PILLAR_NAMES[best_key]


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


def get_recent_video_ids(yt, uploads_playlist_id, max_results=25):
    """Get recent video IDs from uploads playlist. 1 quota unit."""
    resp = yt.playlistItems().list(
        part="contentDetails",
        playlistId=uploads_playlist_id,
        maxResults=max_results,
    ).execute()
    return [item["contentDetails"]["videoId"] for item in resp.get("items", [])]


def get_video_details(yt, video_ids, cutoff_date=None):
    """Get stats and snippets for videos. 1 quota unit per 50 videos.

    If cutoff_date is provided, only returns videos published on or after that date.
    """
    resp = yt.videos().list(
        part="statistics,snippet",
        id=",".join(video_ids),
    ).execute()
    results = []
    for item in resp.get("items", []):
        published = item["snippet"]["publishedAt"][:10]  # "YYYY-MM-DD"
        if cutoff_date and published < cutoff_date:
            continue
        results.append({
            "video_id": item["id"],
            "title": item["snippet"]["title"],
            "description": item["snippet"].get("description", ""),
            "published": published,
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


RESULTS_PER_PILLAR = 5


def scout_all(brand_voice):
    """Scan competitor channels and return a balanced mix across all 4 pillars.

    Collects all qualifying videos (Outlier or Brand Match), assigns each to
    its best-matching pillar, then takes the top 5 from each pillar ranked by
    a combined score (outlier_score + brand_score).
    """
    yt = get_youtube()
    cutoff_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    extra_kw = _extra_keywords_from_voice(brand_voice)

    all_candidates = []

    competitors = load_competitors()
    print(f"  Loaded {len(competitors)} competitors from Competitor Tracker sheet.")
    print(f"  Scanning videos published since {cutoff_date}\n")

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
            video_ids = get_recent_video_ids(yt, channel["uploads_playlist"], max_results=25)
        except Exception as e:
            print(f"    Error fetching videos: {e}, skipping.")
            continue
        if not video_ids:
            print(f"    No videos found, skipping.")
            continue

        videos = get_video_details(yt, video_ids, cutoff_date=cutoff_date)
        if not videos:
            print(f"    No videos in the last 7 days, skipping.")
            continue
        videos = score_videos(videos)

        n_outliers = 0
        n_brand = 0
        for v in videos:
            brand_score = score_brand_match(v, brand_voice, extra_kw)
            v["brand_score"] = brand_score
            is_outlier = v["outlier_score"] >= OUTLIER_THRESHOLD
            is_brand = brand_score >= BRAND_MATCH_MIN

            if not is_outlier and not is_brand:
                continue

            pillar = detect_pillar(v)

            row = {
                "date": v["published"],
                "pillar": pillar,
                "platform": "YouTube",
                "channel": v["channel"],
                "title": v["title"],
                "views": v["views"],
                "outlier_score": v["outlier_score"],
                "brand_score": brand_score,
                "type": "Outlier" if is_outlier else "Brand Match",
                "url": f"https://youtube.com/watch?v={v['video_id']}",
                "hook_transcript": extract_hook(v.get("description", "")),
            }
            all_candidates.append(row)

            if is_outlier:
                n_outliers += 1
            else:
                n_brand += 1

        print(f"    {channel['channel_name']}: {n_outliers} outlier(s), {n_brand} brand match(es)")

    # Group by pillar, take top 5 from each ranked by combined score
    pillar_buckets = {p: [] for p in PILLAR_ORDER}
    for row in all_candidates:
        pillar_buckets[row["pillar"]].append(row)

    combined = []
    for pillar in PILLAR_ORDER:
        bucket = pillar_buckets[pillar]
        bucket.sort(key=lambda x: x["outlier_score"] + x["brand_score"], reverse=True)
        top = bucket[:RESULTS_PER_PILLAR]
        combined.extend(top)
        n_o = sum(1 for r in top if r["type"] == "Outlier")
        n_b = len(top) - n_o
        print(f"  {pillar:30s}: {len(top)} selected ({n_o} outlier, {n_b} brand match) out of {len(bucket)} candidates")

    print(f"\n  Total: {len(combined)} results across {len(PILLAR_ORDER)} pillars")
    return combined


def write_to_sheet(results):
    """Append new result rows to the Daily Outliers tab, skipping duplicates by URL.

    Rows are sorted by pillar order then by combined score descending.
    """
    # Get existing URLs to avoid duplicates (URL is column index 9 with Pillar column)
    existing_urls = get_existing_values(TAB, 9)

    # Filter out duplicates
    new_results = [r for r in results if r["url"] not in existing_urls]
    skipped = len(results) - len(new_results)
    if skipped:
        print(f"  Skipped {skipped} duplicate(s) already in sheet.")

    if not new_results:
        return 0

    # Sort by pillar order, then by combined score descending within each pillar
    pillar_rank = {p: i for i, p in enumerate(PILLAR_ORDER)}
    new_results.sort(key=lambda x: (
        pillar_rank.get(x["pillar"], 99),
        -(x["outlier_score"] + x["brand_score"]),
    ))

    rows = [
        [
            r["date"],
            r["pillar"],
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
        for r in new_results
    ]
    count = append_rows(TAB, rows)
    return count


def run():
    print("Pruning rows older than 7 days from Daily Outliers, Content Calendar, and Brand Match Ideas...")
    pruned_outliers = delete_old_rows("Daily Outliers", date_col_index=0, days=7)
    pruned_calendar = delete_old_rows("Content Calendar", date_col_index=0, days=7)
    pruned_brand = delete_old_rows("Brand Match Ideas", date_col_index=0, days=7)
    print(f"  Pruned {pruned_outliers} old rows from Daily Outliers")
    print(f"  Pruned {pruned_calendar} old rows from Content Calendar")
    print(f"  Pruned {pruned_brand} old rows from Brand Match Ideas\n")

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
    print(f"Done — {count} new rows written to Google Sheets.")

    print("\nVerifying — entries from sheet:")
    records = read_all(TAB)
    current_pillar = None
    for r in records[:min(len(results), 20)]:
        pillar = r.get("Pillar", "?")
        if pillar != current_pillar:
            current_pillar = pillar
            print(f"\n  --- {pillar} ---")
        print(f"  [{r.get('Type','?'):>12}] {r.get('Outlier Score',''):>4}x | B:{r.get('Brand Score',''):>4} | {r.get('Channel','?'):<25} | {r.get('Title','?')}")

    return results


if __name__ == "__main__":
    run()
