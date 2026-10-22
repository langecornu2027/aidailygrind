"""Make today's AI Daily Grind.

    python -m daily_grind              fetch news, write the edition, make the cover, build the site
    python -m daily_grind --fetch-only show what the sources found (no AI call)
    python -m daily_grind --build-only rebuild the site from saved editions
    python -m daily_grind --force      write today's edition again even if it exists
"""

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from . import cover, fetch, render, write

TIMEZONE = ZoneInfo("America/Toronto")

# Short names allowed in .env, and the names the SDKs look for
ENV_ALIASES = {"ANTH_KEY": "ANTHROPIC_API_KEY", "GEMINI_KEY": "GEMINI_API_KEY",
               "EMAIL_TOKEN": "CLOUDFLARE_API_TOKEN"}


def load_env() -> None:
    """Read keys from .env (on your Mac). On GitHub, they come from repo secrets."""
    env_file = render.ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(name.strip(), value.strip().strip("\"'"))
    for short, full in ENV_ALIASES.items():
        if os.environ.get(short):
            os.environ.setdefault(full, os.environ[short])


def add_cover(day: str, edition: dict) -> None:
    """Make today's cover image if it is missing. A failure never stops the edition."""
    path = render.COVERS / f"{day}.jpg"
    if path.exists():
        return
    if not os.environ.get("GEMINI_API_KEY"):
        print("☕ No GEMINI_API_KEY, so no cover image today.")
        return
    scene = edition.get("cover_scene") or f"A visual metaphor for: {edition['headline']}"
    print("☕ Asking Nano Banana for the cover image...")
    try:
        cover.make_cover(scene, path)
        print(f"  Saved {path.relative_to(render.ROOT)}")
    except Exception as exc:
        print(f"  ✗ No cover today: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Make today's AI Daily Grind.")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    load_env()

    today = datetime.now(TIMEZONE).date()
    out = render.EDITIONS / f"{today.isoformat()}.json"

    if not args.build_only:
        if out.exists() and not args.force and not args.fetch_only:
            print(f"☕ Today's edition already exists ({out.name}). Use --force to write it again.")
        else:
            print("☕ Reading the sources...")
            items = fetch.fetch_all()
            print(f"  {len(items)} fresh stories in total")
            if args.fetch_only:
                for item in items:
                    print(f"  [{item.source}] {item.title}")
                return
            if not items:
                raise SystemExit("No stories found. Check your internet connection or sources.")

            print("☕ Writing the Morning Tokens...")
            older = [p for p in sorted(render.EDITIONS.glob("*.json")) if p.stem < today.isoformat()]
            yesterday = ([t["title"] for t in json.loads(older[-1].read_text(encoding="utf-8"))["tokens"]]
                         if older else [])
            edition = write.write_edition(fetch.to_dicts(items), render.nice_date(today.isoformat()), yesterday)
            render.EDITIONS.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  Saved {out.relative_to(render.ROOT)} ({len(edition['tokens'])} Morning Tokens)")

        if out.exists() and not args.fetch_only:
            add_cover(today.isoformat(), json.loads(out.read_text(encoding="utf-8")))

    site = render.build_site()
    print(f"☕ Site ready: {site / 'index.html'}")


if __name__ == "__main__":
    main()
