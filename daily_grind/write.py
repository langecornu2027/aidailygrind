"""Ask Claude to pick the most important stories and write today's AI Daily Grind."""

import json
from pathlib import Path

import anthropic

MODEL = "claude-opus-5-5"
ROOT = Path(__file__).resolve().parent.parent

SYSTEM = """You are the writer of The AI Daily Grind, a daily recap of what is happening in AI.
The reader opens The AI Daily Grind with their morning coffee. In five minutes, they want to know
what really matters in AI today, explained in simple English.

You will get a list of fresh stories from news sites, AI company blogs, community sites
(Hacker News, Reddit), a daily AI podcast, AI risk and safety sources, research papers,
and new AI projects trending on GitHub. Many are small, repeated, or off-topic.
Your job:

1. Find the 5 to 7 most important AI stories. Each one becomes a "Morning Token".
   - Prefer stories that matter to many people: big launches, new tools people can use,
     important research, policy, safety, jobs, big business moves.
   - When several sources talk about the same thing, merge them into one token and
     list every useful source. A story covered by many sources is usually important.
   - Community buzz (many points or upvotes) is a good signal, but not proof.
   - Skip stories that are not really about AI.
   - The author cares about AI risk and safety. When a risk or safety source has real
     news or a strong warning, give it a token.
   - When a trending GitHub project is useful or surprising for normal people, give it
     a token (tag "Open source") and say what it does and who could use it.
   - Do not repeat a story from yesterday's tokens (listed in the request), unless there
     is real new information. Then say what is new.
   - Put the most important token first.
2. Write each token in the author's voice (below). A token is a short article, not a
   one-liner: give the context, the key facts (who, what, numbers, dates when known),
   and what happens next. Use only facts from the stories you
   were given. If a detail is not in the input, do not invent it. If something is only
   a rumour or early research, say so.
3. Write the daily top recap (the intro, 2 or 3 paragraphs) and a short closing word.
4. Describe a scene for today's cover illustration.

The author's voice guide:
<voice>
{voice}
</voice>"""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One short line that sums up the AI mood of the day.",
        },
        "intro": {
            "type": "string",
            "description": (
                "The daily top recap, in 2 or 3 short paragraphs separated by a blank line "
                "(8 to 12 short sentences in total). Say hello, then tell the big picture of "
                "the day: what the main stories are, how they connect, and the trend behind "
                "them. End with what to watch. Do not just list the tokens."
            ),
        },
        "tokens": {
            "type": "array",
            "description": "The Morning Tokens, most important first. 5 to 7 items.",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short, clear title. No clickbait."},
                    "tag": {
                        "type": "string",
                        "enum": ["Launch", "Tool", "Open source", "Research", "Business",
                                 "Policy", "Safety", "Community"],
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "What happened, in 2 or 3 short paragraphs separated by a blank line. "
                            "6 to 10 short, simple sentences in total. Context first, then the "
                            "key facts, then what happens next."
                        ),
                    },
                    "why_it_matters": {
                        "type": "string",
                        "description": "Two or three sentences: why the reader should care.",
                    },
                    "share_text": {
                        "type": "string",
                        "description": (
                            "A post to share this token on social media (LinkedIn, X), in the "
                            "author's voice. Max 220 characters, no hashtags, no link "
                            "(the link is added later), at most one emoji."
                        ),
                    },
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["name", "url"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "tag", "summary", "why_it_matters", "share_text", "sources"],
                "additionalProperties": False,
            },
        },
        "last_word": {
            "type": "string",
            "description": "Le dernier mot: one or two sentences, a personal thought to close.",
        },
        "cover_scene": {
            "type": "string",
            "description": (
                "Scene for today's cover illustration, for an image model. 2 or 3 sentences "
                "that show the top story (or the mood of the day) as a simple visual metaphor. "
                "Describe objects, characters and setting only. No text, logos, brand names, "
                "or real people. The art style is added later, so do not describe it."
            ),
        },
    },
    "required": ["headline", "intro", "tokens", "last_word", "cover_scene"],
    "additionalProperties": False,
}


def write_edition(items: list[dict], date_label: str, yesterday: list[str] | None = None) -> dict:
    voice = (ROOT / "voice.md").read_text(encoding="utf-8")
    stories = [
        {k: v for k, v in item.items() if k in ("source", "kind", "title", "url", "summary", "score") and v}
        for item in items
    ]
    prompt = (
        f"Today is {date_label}. Here are the {len(stories)} fresh stories, as JSON:\n\n"
        f"{json.dumps(stories, ensure_ascii=False, indent=1)}\n\n"
        f"Yesterday's tokens (do not repeat): {json.dumps(yesterday or [], ensure_ascii=False)}\n\n"
        "Write today's AI Daily Grind."
    )

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM.format(voice=voice),
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        # If a safety check declines the request, Anthropic retries on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined to write today's edition: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Claude ran out of room before finishing. Raise max_tokens.")

    text = next(block.text for block in response.content if block.type == "text")
    edition = json.loads(text)
    usage = response.usage
    print(f"  Claude used {usage.input_tokens} input + {usage.output_tokens} output tokens")
    return edition
