"""
script_writer.py — Takes outlier data from trend_scout, loads Brand Voice from
the sheet, uses Claude to generate video scripts in Jake's voice, and writes
results to two tabs:

  - Content Calendar      — scripts generated from Outlier videos
  - Brand Match Ideas     — scripts generated from Brand Match videos

Columns (Content Calendar): Date, Title, Hook, Script, Shorts Script
Columns (Brand Match Ideas): Date, Pillar, Source Channel, Source Title, Title, Hook, Script, Shorts Script
"""

import os
import sys
import re
import datetime
import anthropic
from dotenv import load_dotenv
from sheets_helper import append_rows, read_all, clear_data_rows

load_dotenv()

TAB_OUTLIERS = "Content Calendar"
TAB_BRAND = "Brand Match Ideas"

# ── Pillar detection ───────────────────────────────────────────────

PILLAR_PATTERNS = {
    "Real Estate + AI": [
        "real estate", "realtor", "listing", "buyer", "seller", "lead gen",
        "open house", "mortgage", "property", "mls", "brokerage", "fsbo",
        "expired listing", "isa", "door knocking",
    ],
    "Go High Level": [
        "go high level", "gohighlevel", "highlevel", "ghl", "high level",
        "sub-account", "subaccount", "snapshot", "clickfunnels", "kartra",
        "saas mode", "white label", "whitelabel",
    ],
    "How to Make Money with AI": [
        "make money", "income", "monetize", "side hustle", "ai business",
        "business model", "case study", "recurring revenue", "passive income",
        "pricing", "charge", "sell ai", "ai agency", "smma",
    ],
    "AI Tools & Automation": [
        "ai", "automation", "workflow", "chatgpt", "claude", "claude code",
        "gpt", "llm", "agent", "no-code", "zapier", "make.com", "n8n",
        "prompt", "lovable", "gemini", "notebooklm", "notebook lm",
        "higgsfield", "anthropic",
    ],
}


def detect_pillar(title, channel=""):
    """Detect which content pillar a video best matches. Returns pillar name."""
    text = (title + " " + channel).lower()
    best_pillar = "AI Tools & Automation"  # default
    best_hits = 0
    for pillar, keywords in PILLAR_PATTERNS.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > best_hits:
            best_hits = hits
            best_pillar = pillar
    return best_pillar

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

=== 4 CONTENT PILLARS ===
Jake's channel covers 4 pillars. Every script must fit one of these:

1. AI TOOLS & AUTOMATION — practical AI tools, workflows, and automation for entrepreneurs and business owners. Think Claude, ChatGPT, Zapier, n8n, Make.com, AI agents.

2. HOW TO MAKE MONEY WITH AI — AI business models, income streams, operator mindset, real case studies. How to package AI skills into a service or product.

3. REAL ESTATE + AI — how real estate agents use AI for lead generation, client follow-up automation, sales funnels, market analysis, listing content, and modernizing their business.

4. GO HIGH LEVEL (GHL) — GHL tutorials, CRM automation, webinar funnels, landing pages, SMS/email sequences, sub-accounts, white-label SaaS. Practical walkthroughs for agency owners and entrepreneurs.
=== END PILLARS ===

RULES:
- Every script must match Jake's tone, vocabulary, and style above.
- Always use words from the "Words To Use" list naturally throughout.
- NEVER use any word from the "Words To Avoid" list.
- Write as a practitioner who has actually done this — not a commentator.
- Use short, punchy sentences. No fluff.
- Identify which content pillar the outlier video maps to and write the script from that angle.
- If the video touches real estate, lean into the real estate + AI angle.
- If the video touches GHL/funnels/CRM, lean into the Go High Level angle.
- Always connect back to Jake's operator perspective — he builds and deploys, not just comments."""


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

You MUST follow this exact 8-step structure in order. Each step MUST start on its own line with the exact label followed by a colon. This formatting is critical — a dashboard parses these labels to display each step as a separate card.

STEP 1 - PATTERN INTERRUPT / VISUAL HOOK:
Open with something visually or verbally jarring that stops the scroll. A bold claim, a weird visual, a contradictory statement. The viewer should think "wait, what?"

STEP 2 - MIRROR THE VIEWER:
Call out exactly where the viewer is right now. Their frustration, their situation, their daily reality. Make them feel seen. "You're probably doing X right now and it's killing you."

STEP 3 - REVEAL THE OPPORTUNITY:
Show them what's now possible that wasn't before. Paint the picture of the new reality. This is the "what if" moment.

STEP 4 - EXPOSE THE GAP:
Explain why most people are failing at this. What they're getting wrong. What the common mistakes are. Build tension between where they are and where they could be.

STEP 5 - PROMISE THE TRANSFORMATION:
Bridge the gap. Tell them exactly what changes when they do this right. Be specific — numbers, timeframes, outcomes.

STEP 6 - AUTHORITY THROUGH SYSTEMS:
Establish Jake's credibility by referencing his actual systems, results, or experience. Not bragging — just showing receipts. "Here's what we built..." or "In our operation..."

STEP 7 - THE BREAKDOWN:
Deliver 3 main teaching points. This is the meat of the video. Each point should be actionable and specific. Label them clearly (Point 1, Point 2, Point 3).

STEP 8 - CALL TO ACTION:
Point viewers to the AI Operations Lab. Make it a natural next step, not a hard sell. Frame it as "if you want the full system" or "if you want to go deeper."]

Be original. Don't copy the outlier — use it as inspiration for Jake's unique operator angle."""


def build_shorts_prompt(outlier, full_script_title):
    """Build the user message for generating a YouTube Shorts script."""
    return f"""Take this video concept and create a punchy YouTube Shorts script (under 30 seconds, max 75 words).

ORIGINAL VIDEO CONCEPT:
- Title: {full_script_title}
- Inspired by outlier: {outlier['title']} ({outlier['views']:,} views)

Write the shorts script in this exact format:

SHORTS_SCRIPT:
[A rapid-fire, vertical-video script. One core takeaway. Under 30 seconds, max 75 words.
Open with a scroll-stopping pattern interrupt (Step 1), mirror the viewer's pain (Step 2),
deliver one key insight from the breakdown (Step 7), and end with a punchy CTA pointing to the AI Operations Lab (Step 8).
No fluff, no intro, no "hey guys". Just straight value.
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


STEP_LABELS = [
    "STEP 1 - PATTERN INTERRUPT / VISUAL HOOK:",
    "STEP 2 - MIRROR THE VIEWER:",
    "STEP 3 - REVEAL THE OPPORTUNITY:",
    "STEP 4 - EXPOSE THE GAP:",
    "STEP 5 - PROMISE THE TRANSFORMATION:",
    "STEP 6 - AUTHORITY THROUGH SYSTEMS:",
    "STEP 7 - THE BREAKDOWN:",
    "STEP 8 - CALL TO ACTION:",
]


def normalize_steps(script_body):
    """Ensure every step label matches the exact canonical format.

    Handles variations like missing colons, extra whitespace, slightly
    different wording, or missing subtitles.  The dashboard splits on
    'STEP X -' so this must be exact.
    """
    # Pattern matches lines like "STEP 1 - ...", "STEP 1:", "**STEP 1 -...**"
    step_pattern = re.compile(
        r"^\s*\**\s*STEP\s+(\d)\s*[-–—:]\s*.*$", re.IGNORECASE
    )
    lines = script_body.split("\n")
    result = []
    for line in lines:
        m = step_pattern.match(line)
        if m:
            step_num = int(m.group(1))
            if 1 <= step_num <= 8:
                result.append(STEP_LABELS[step_num - 1])
                continue
        result.append(line)
    return "\n".join(result)


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
    script_body = normalize_steps(script_body)
    return title, hook, script_body


def generate_content_ideas(outliers, brand_voice):
    """Generate scripts for all videos using Claude + Brand Voice."""
    today = datetime.date.today().isoformat()
    ideas = []
    count = len(outliers)

    for i, o in enumerate(outliers):
        video_type = o.get("type", "Outlier")
        pillar = detect_pillar(o["title"], o.get("channel", ""))
        print(f"  [{i+1}/{count}] [{video_type} | {pillar}] {o['title'][:50]}...")

        raw_script = generate_script(o, brand_voice)
        title, hook, script_body = parse_script(raw_script)
        final_title = title or o["title"]

        print(f"          Generating shorts script...")
        shorts_body = generate_shorts_script(o, final_title, brand_voice)

        ideas.append({
            "date": today,
            "type": video_type,
            "pillar": pillar,
            "source_channel": o.get("channel", ""),
            "source_title": o["title"],
            "title": final_title,
            "hook": hook,
            "script_body": script_body,
            "shorts_script": shorts_body,
        })

    return ideas


def write_ideas_to_sheets(ideas):
    """Route scripts to the correct tab based on type.

    Outlier  → Content Calendar
    Brand Match → Brand Match Ideas

    Script bodies are stored with RAW input to preserve newlines in cells.
    """
    outlier_ideas = [i for i in ideas if i["type"] == "Outlier"]
    brand_ideas = [i for i in ideas if i["type"] == "Brand Match"]

    outlier_count = 0
    brand_count = 0

    if outlier_ideas:
        rows = [
            [i["date"], i["title"], i["hook"], i["script_body"], i["shorts_script"]]
            for i in outlier_ideas
        ]
        outlier_count = append_rows(TAB_OUTLIERS, rows, value_input_option="RAW")

    if brand_ideas:
        rows = [
            [
                i["date"], i["pillar"], i["source_channel"], i["source_title"],
                i["title"], i["hook"], i["script_body"], i["shorts_script"],
            ]
            for i in brand_ideas
        ]
        brand_count = append_rows(TAB_BRAND, rows, value_input_option="RAW")

    return outlier_count, brand_count


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

    n_outlier = sum(1 for o in outliers if o.get("type") == "Outlier")
    n_brand = sum(1 for o in outliers if o.get("type") == "Brand Match")
    print(f"Generating scripts from {len(outliers)} videos ({n_outlier} outliers, {n_brand} brand matches)...\n")

    ideas = generate_content_ideas(outliers, brand_voice)

    print(f"\nCreated {len(ideas)} scripts. Writing to sheets...")
    outlier_count, brand_count = write_ideas_to_sheets(ideas)
    print(f"  Content Calendar:   {outlier_count} outlier scripts")
    print(f"  Brand Match Ideas:  {brand_count} brand match scripts")

    print("\nSaving full scripts locally...")
    save_scripts_locally(ideas)

    print("\nVerifying — Content Calendar:")
    records = read_all(TAB_OUTLIERS)
    for r in records[-min(outlier_count, 3):]:
        print(f"  {r.get('Date','?')} | {r.get('Your Title','?')}")

    print("\nVerifying — Brand Match Ideas:")
    records = read_all(TAB_BRAND)
    for r in records[-min(brand_count, 3):]:
        print(f"  {r.get('Date','?')} | [{r.get('Pillar','?')}] {r.get('Your Title','?')}")

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
                "type": r.get("Type", "Outlier"),
                "pillar": r.get("Pillar", ""),
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
