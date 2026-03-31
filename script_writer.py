"""
script_writer.py — Takes outlier data from trend_scout, loads Brand Voice from
the sheet, uses Claude to generate video scripts in Jake's voice, and writes
results to the 'Content Calendar' tab.

Columns: Date, Title, Hook, Script, Shorts Script
"""

import os
import sys
import datetime
import anthropic
from dotenv import load_dotenv
from sheets_helper import append_rows, read_all, clear_data_rows

load_dotenv()

TAB = "Content Calendar"

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def load_brand_voice():
    """Load Brand Voice key-value pairs from the sheet."""
    records = read_all("Brand Voice")
    voice = {}
    for r in records:
        voice[r.get("Key", "")] = r.get("Value", "")
    return voice


def build_system_prompt(brand_voice):
    """Build the system prompt from Brand Voice guidelines."""
    return f"""You are a scriptwriter for Jake Randolph's YouTube channel. Every script you write MUST follow Jake's brand voice exactly. Never deviate from these rules:

=== BRAND VOICE ===
TONE: {brand_voice.get('Tone', '')}

TARGET AUDIENCE (ICA): {brand_voice.get('ICA', '')}

TOPICS TO COVER: {brand_voice.get('Topics', '')}

HOOKS THAT WORK: {brand_voice.get('Hooks That Work', '')}

WORDS TO USE: {brand_voice.get('Words You Use', '')}

WORDS TO AVOID: {brand_voice.get('Words You Avoid', '')}
=== END BRAND VOICE ===

RULES:
- Every script must match Jake's tone, vocabulary, and style above.
- Always use words from the "Words To Use" list naturally throughout.
- NEVER use any word from the "Words To Avoid" list.
- Write as a practitioner who has actually done this — not a commentator.
- Use short, punchy sentences. No fluff."""


def build_user_prompt(outlier):
    """Build the user message with the outlier data and output format."""
    return f"""An outlier video went viral on a competitor channel. Write an ORIGINAL ~2 minute video script (approximately 300-400 words) that Jake can film as his own unique take.

OUTLIER VIDEO:
- Title: {outlier['title']}
- Channel: {outlier['channel']}
- Views: {outlier['views']:,}
- Hook from description: {outlier.get('hook_transcript', '')}

Write the script in this exact format:

TITLE: [A catchy title inspired by the outlier's vibe and energy — mirror the structure, rhythm, and emotional trigger that made it click, but rewrite it in Jake's voice with his angle. Do NOT copy word-for-word. Do NOT make it generic or bland.]
HOOK: [The first 3 seconds — must stop the scroll. Use one of Jake's proven hook patterns.]
SCRIPT:
[The full script. ~2 minutes long (300-400 words). Short punchy sentences. Practitioner tone — like a guy who's actually done this.
Include [B-ROLL: description] cues where relevant.
Use Jake's vocabulary from the brand voice. Avoid ALL words on the avoid list.
Structure: Hook → Problem/Context → Jake's Take/Experience → Actionable Insight → CTA]

Be original. Don't copy the outlier — use it as inspiration for Jake's unique operator angle."""


def build_shorts_prompt(outlier, full_script_title):
    """Build the user message for generating a YouTube Shorts script."""
    return f"""Take this video concept and create a punchy YouTube Shorts script (under 30 seconds, max 75 words).

ORIGINAL VIDEO CONCEPT:
- Title: {full_script_title}
- Inspired by outlier: {outlier['title']} ({outlier['views']:,} views)

Write the shorts script in this exact format:

SHORTS_SCRIPT:
[A rapid-fire, vertical-video script. One core takeaway. Open with a scroll-stopping first line.
No fluff, no intro, no "hey guys". Just straight value. End with a punchy closer or CTA.
Must follow Jake's brand voice exactly — use his words, avoid the avoid list.]"""


def generate_script(outlier, brand_voice):
    """Use Claude to generate a video script from an outlier + brand voice."""
    system = build_system_prompt(brand_voice)
    user_msg = build_user_prompt(outlier)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return message.content[0].text


def generate_shorts_script(outlier, full_script_title, brand_voice):
    """Use Claude to generate a YouTube Shorts script from the same outlier."""
    system = build_system_prompt(brand_voice)
    user_msg = build_shorts_prompt(outlier, full_script_title)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = message.content[0].text
    # Parse out just the script body
    if "SHORTS_SCRIPT:" in raw:
        return raw.split("SHORTS_SCRIPT:", 1)[1].strip()
    return raw.strip()


def parse_script(raw_script):
    """Parse the generated script into title, hook, and full script."""
    title = ""
    hook = ""
    lines = raw_script.strip().split("\n")
    in_script = False
    script_lines = []

    for line in lines:
        if line.startswith("TITLE:"):
            title = line.replace("TITLE:", "").strip()
        elif line.startswith("HOOK:"):
            hook = line.replace("HOOK:", "").strip()
        elif line.startswith("SCRIPT:"):
            in_script = True
        elif in_script:
            script_lines.append(line)

    script_body = "\n".join(script_lines).strip()
    return title, hook, script_body


def generate_content_ideas(outliers, brand_voice):
    """Generate scripts for top outliers using Claude + Brand Voice."""
    today = datetime.date.today().isoformat()
    ideas = []
    count = len(outliers)

    for i, o in enumerate(outliers):
        print(f"  [{i+1}/{count}] Generating script for: {o['title'][:50]}...")
        raw_script = generate_script(o, brand_voice)
        title, hook, script_body = parse_script(raw_script)
        final_title = title or o["title"]

        print(f"          Generating shorts script...")
        shorts_body = generate_shorts_script(o, final_title, brand_voice)

        ideas.append({
            "date": today,
            "title": final_title,
            "hook": hook,
            "script_body": script_body,
            "shorts_script": shorts_body,
        })

    return ideas


def write_ideas_to_sheet(ideas):
    """Append rows to the Content Calendar tab including full script."""
    rows = [
        [
            i["date"],
            i["title"],
            i["hook"],
            i["script_body"],
            i["shorts_script"],
        ]
        for i in ideas
    ]
    count = append_rows(TAB, rows)
    return count


def save_scripts_locally(ideas):
    """Save full scripts to local files for review."""
    scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    for idea in ideas:
        safe_title = "".join(c for c in idea["title"] if c.isalnum() or c in " -_")[:50].strip()
        filename = f"{idea['date']}_{safe_title}.md"
        filepath = os.path.join(scripts_dir, filename)
        with open(filepath, "w") as f:
            f.write(f"# {idea['title']}\n\n")
            f.write(f"**Hook:** {idea['hook']}\n\n")
            f.write(f"**Date:** {idea['date']}\n\n")
            f.write(f"---\n\n")
            f.write(idea["script_body"])
            f.write(f"\n\n---\n\n## Shorts Script\n\n")
            f.write(idea["shorts_script"])
            f.write("\n")
        print(f"  Saved: scripts/{filename}")


def run(outliers=None):
    if not outliers:
        print("No outlier data provided. Run trend_scout.py first.")
        return

    print("Loading Brand Voice from sheet...")
    brand_voice = load_brand_voice()
    print(f"  Loaded {len(brand_voice)} brand voice keys: {', '.join(brand_voice.keys())}\n")

    print(f"Generating video scripts from {len(outliers)} outliers using Claude + Brand Voice...\n")
    ideas = generate_content_ideas(outliers, brand_voice)

    print(f"\nCreated {len(ideas)} scripts. Writing to '{TAB}' tab...")
    count = write_ideas_to_sheet(ideas)
    print(f"Done — {count} rows written to Google Sheets.")

    print("\nSaving full scripts locally...")
    save_scripts_locally(ideas)

    print("\nVerifying — last entries from sheet:")
    records = read_all(TAB)
    for r in records[-len(ideas):]:
        print(f"  {r.get('Date','?')} | {r.get('Your Title','?')}")
        print(f"    Hook: {str(r.get('Hook',''))[:80]}")

    return ideas


if __name__ == "__main__":
    if "--from-sheet" in sys.argv:
        print("Reading outliers from Google Sheet...")
        records = read_all("Daily Outliers")
        outliers = [
            {
                "title": r.get("Title", ""),
                "channel": r.get("Channel", ""),
                "views": int(str(r.get("Views", 0)).replace(",", "")),
                "hook_transcript": r.get("Hook Transcript", ""),
            }
            for r in records
        ]
        seen = {}
        for o in outliers:
            seen[o["title"]] = o
        outliers = sorted(seen.values(), key=lambda x: x["views"], reverse=True)
        print(f"Loaded {len(outliers)} outliers from sheet.\n")
    else:
        from trend_scout import run as scout_run
        outliers = scout_run()
        print()

    print("=" * 60)
    print("PHASE 2: Script Generation (Brand Voice)")
    print("=" * 60 + "\n")
    run(outliers)
