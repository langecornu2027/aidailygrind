"""Le Café Noir: François's weekly editorial, every Thursday.

Two steps:
1. Research: the writer model reads the last 7 days of Morning Tokens and uses web search
   to find the week's most important and controversial AI stories (with source links).
2. Writing: it writes the editorial in François's voice and from his perspective
   (voice.md + perspective.md), as structured JSON.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import anthropic

from .write import MODEL

ROOT = Path(__file__).resolve().parent.parent
EDITORIALS = ROOT / "data" / "editorials"
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

RESEARCH_SYSTEM = """You are the research assistant for "Le Café Noir", a weekly AI editorial.
Today is {today}. Your job: find what really happened in AI in the last 7 days
({start} to {today}) and which stories are the most debated or controversial.

You get the week's Morning Tokens (already summarized). Use web search to check the
biggest stories, find the controversy around them (who disagrees, and why), and catch
any important AI story of the week that the tokens missed. Prefer events from the last
7 days only.

Answer with a research brief in plain text:
- The 4 to 6 most important or controversial stories of the week. For each: what happened
  (facts, numbers, dates), the two sides of the debate, and 1 to 3 source links (URLs).
- Then: the one story or theme you think is the strongest for a provocative but fair
  editorial from the author's point of view (below), and why.
Only facts you found. Say clearly when something is a claim, a rumour or disputed.

The author's point of view:
<perspective>
{perspective}
</perspective>"""

WRITE_SYSTEM = """You write "Le Café Noir", the weekly editorial of The AI Daily Grind, in the
voice and from the perspective of its author, François Gravel. It is his personal take
on what is happening in AI this week. It is an opinion piece: take a clear position.

Rules:
- Pick ONE strong theme from the research brief (you can connect 2 or 3 stories to it).
  Prefer the most controversial topic that matters for people.
- Be provocative to grab attention and start debate: a bold title and a strong first
  line. But stay fair: give credit where due, show the other side, then say why the
  author disagrees or worries. No doom, no conspiracy, no insults.
- Show both sides of the author: passionate about AI, and conscious of the risks.
- Use only facts from the research brief and the tokens. If a fact is disputed, say so.
  When you mention a past event (like the Hugging Face incident), be precise.
- Simple English, short sentences, like the author's daily recap. A little French is OK.
- 700 to 1,000 words in the body.
- End with a short call to action (what readers, companies or governments should do),
  then one sharp question to readers.

The author's voice guide:
<voice>
{voice}
</voice>

The author's perspective on AI (follow it closely; it is his opinion, not yours):
<perspective>
{perspective}
</perspective>"""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Bold, provocative but honest title. Max 90 characters."},
        "dek": {"type": "string", "description": "One-sentence subtitle that sums up the position."},
        "body": {
            "type": "string",
            "description": (
                "The editorial, 700 to 1,000 words. Short paragraphs separated by a blank line. "
                "You may use 2 to 4 short section titles, each on its own line starting with '## '. "
                "No other markdown."
            ),
        },
        "call_to_action": {"type": "string", "description": "2 or 3 sentences: what readers, companies or governments should do."},
        "question": {"type": "string", "description": "One sharp question to readers, to start the debate."},
        "sources": {
            "type": "array",
            "description": "The 3 to 8 main sources used, from the research brief.",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                "required": ["name", "url"],
                "additionalProperties": False,
            },
        },
        "hashtags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "3 to 5 hashtags for sharing the editorial on LinkedIn/Facebook, most relevant first, "
                            "e.g. #AISafety #Cybersecurity #OpenAI. CamelCase, no spaces, start with #. "
                            "Mix one broad tag (#AI) with specific ones (topic, company, product)."
                        ),
                    },
        "social_post": {
            "type": "string",
            "description": (
                "A LinkedIn post to share the editorial, in the author's voice: a provocative hook "
                "with one emoji, 2 or 3 short lines with the position, then the question. "
                "Max 700 characters, no hashtags, no link."
            ),
        },
        "cover_scene": {
            "type": "string",
            "description": (
                "Scene for the cover illustration: a simple, strong visual metaphor of the editorial's "
                "theme, 2 or 3 sentences. Objects, characters, setting only. No text, logos or real people."
            ),
        },
    },
    "required": ["title", "dek", "body", "call_to_action", "question", "sources", "hashtags", "social_post",
                 "cover_scene"],
    "additionalProperties": False,
}


def week_tokens(today: date, editions_dir: Path) -> list[dict]:
    out = []
    for path in sorted(editions_dir.glob("*.json")):
        day = date.fromisoformat(path.stem)
        if today - timedelta(days=7) < day <= today:
            e = json.loads(path.read_text(encoding="utf-8"))
            for t in e["tokens"]:
                out.append({"date": path.stem, "title": t["title"], "tag": t["tag"], "summary": t["summary"],
                            "why_it_matters": t["why_it_matters"], "sources": t.get("sources", [])})
    return out


def research(client: anthropic.Anthropic, today: date, tokens: list[dict], perspective: str) -> str:
    start = today - timedelta(days=6)
    messages = [{"role": "user", "content": (
        f"This week's Morning Tokens ({len(tokens)}), as JSON:\n\n"
        f"{json.dumps(tokens, ensure_ascii=False, indent=1)}\n\nWrite the research brief.")}]
    system = RESEARCH_SYSTEM.format(today=today.isoformat(), start=start.isoformat(), perspective=perspective)
    for _ in range(6):  # web search can pause a long turn; resume it
        with client.beta.messages.stream(
            model=MODEL, max_tokens=32000, system=system, messages=messages, tools=[WEB_SEARCH],
            thinking={"type": "adaptive"}, output_config={"effort": "medium"}, **FALLBACK,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise RuntimeError(f"The model declined the research: {response.stop_details}")
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
    brief = "\n".join(block.text for block in response.content if block.type == "text").strip()
    print(f"  Research brief: {len(brief.split())} words, {response.usage.input_tokens} input tokens")
    return brief


def write_editorial(today: date, editions_dir: Path) -> dict:
    voice = (ROOT / "voice.md").read_text(encoding="utf-8")
    perspective = (ROOT / "perspective.md").read_text(encoding="utf-8")
    tokens = week_tokens(today, editions_dir)
    client = anthropic.Anthropic()

    brief = research(client, today, tokens, perspective)
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=WRITE_SYSTEM.format(voice=voice, perspective=perspective),
        messages=[{"role": "user", "content": (
            f"Today is {today.isoformat()}. Research brief for this week:\n\n<brief>\n{brief}\n</brief>\n\n"
            f"This week's Morning Tokens:\n{json.dumps(tokens, ensure_ascii=False)}\n\n"
            "Write this week's Le Café Noir.")}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        **FALLBACK,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"The model declined to write the editorial: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("The editorial was cut off. Raise max_tokens.")
    text = next(block.text for block in response.content if block.type == "text")
    editorial = json.loads(text)
    print(f"  Writer model used {response.usage.input_tokens} input + {response.usage.output_tokens} output tokens")
    return editorial
