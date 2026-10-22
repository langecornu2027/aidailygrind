"""Collect fresh AI stories from all sources."""

import calendar
import html
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict

import certifi
import feedparser

from . import sources

USER_AGENT = "CafeIA/1.0 (daily AI recap)"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# Words that tell us a Hacker News story is about AI
AI_WORDS = re.compile(
    r"\b(AI|A\.I\.|LLMs?|GPT|Claude|Anthropic|OpenAI|Gemini|DeepMind|Llama|Mistral|"
    r"machine learning|neural|transformer|chatbot|agents?|model|inference|diffusion|"
    r"Copilot|Hugging ?Face|Nvidia|AGI|deep learning)\b",
    re.IGNORECASE,
)


@dataclass
class Item:
    source: str
    kind: str
    title: str
    url: str
    summary: str
    published: float  # unix time, 0 if unknown
    score: int = 0  # points / upvotes when the source has them


def _clean(text: str, limit: int = 500) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _get(url: str, retries: int = 2) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and retries:  # rate limited: wait and try again
            time.sleep(10)
            return _get(url, retries - 1)
        raise


def _get_json(url: str):
    return json.loads(_get(url))


def fetch_feed(name: str, kind: str, url: str, since: float) -> list[Item]:
    parsed = feedparser.parse(_get(url))
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(parsed.bozo_exception)
    items = []
    for entry in parsed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = calendar.timegm(stamp) if stamp else 0
        if published and published < since:
            continue
        items.append(Item(
            source=name,
            kind=kind,
            title=_clean(entry.get("title", ""), 200),
            url=entry.get("link", ""),
            summary=_clean(entry.get("summary", "")),
            published=published,
        ))
    return items[: sources.MAX_PER_SOURCE]


def fetch_hacker_news(since: float) -> list[Item]:
    url = (
        "https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=200"
        f"&numericFilters=created_at_i>{int(since)},points>={sources.HN_MIN_POINTS}"
    )
    items = []
    for hit in _get_json(url)["hits"]:
        title = hit.get("title") or ""
        if not AI_WORDS.search(title):
            continue
        items.append(Item(
            source="Hacker News",
            kind="community",
            title=title,
            url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
            summary=f"{hit.get('num_comments', 0)} comments on Hacker News",
            published=hit.get("created_at_i", 0),
            score=hit.get("points", 0),
        ))
    items.sort(key=lambda i: i.score, reverse=True)
    return items[: sources.MAX_PER_SOURCE]


def fetch_hf_papers() -> list[Item]:
    items = []
    for entry in _get_json("https://huggingface.co/api/daily_papers"):
        paper = entry.get("paper", {})
        upvotes = paper.get("upvotes", 0)
        if upvotes < sources.HF_MIN_UPVOTES:
            continue
        items.append(Item(
            source="Hugging Face Papers",
            kind="research",
            title=_clean(paper.get("title", ""), 200),
            url=f"https://huggingface.co/papers/{paper.get('id', '')}",
            summary=_clean(paper.get("summary", "")),
            published=0,
            score=upvotes,
        ))
    items.sort(key=lambda i: i.score, reverse=True)
    return items[: sources.MAX_PER_SOURCE]


def fetch_all(verbose: bool = True) -> list[Item]:
    """Fetch every source. A broken source is skipped, never fatal."""
    since = time.time() - sources.LOOKBACK_HOURS * 3600
    jobs = [(name, lambda n=name, k=kind, u=url: fetch_feed(n, k, u, since))
            for name, kind, url in sources.FEEDS]
    jobs += [("Hacker News", lambda: fetch_hacker_news(since)),
             ("Hugging Face Papers", fetch_hf_papers)]

    all_items, seen = [], set()
    for name, job in jobs:
        try:
            found = job()
        except Exception as exc:  # one bad feed should not stop the morning coffee
            if verbose:
                print(f"  ✗ {name}: {exc}")
            continue
        fresh = [i for i in found if i.url and i.url not in seen]
        seen.update(i.url for i in fresh)
        all_items.extend(fresh)
        if verbose:
            print(f"  ✓ {name}: {len(fresh)} items")
    return all_items


def to_dicts(items: list[Item]) -> list[dict]:
    return [asdict(i) for i in items]
