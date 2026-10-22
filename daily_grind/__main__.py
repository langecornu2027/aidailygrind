"""Make today's AI Daily Grind.

    python -m daily_grind              fetch news, ask Claude, save, build the site
    python -m daily_grind --fetch-only show what the sources found (no Claude call)
    python -m daily_grind --build-only rebuild the site from saved editions
    python -m daily_grind --force      write today's edition again even if it exists
"""

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from . import fetch, render, write

TIMEZONE = ZoneInfo("America/Toronto")


def main() -> None:
    parser = argparse.ArgumentParser(description="Make today's AI Daily Grind.")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

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

            print("☕ Asking Claude to pick the Morning Tokens...")
            edition = write.write_edition(fetch.to_dicts(items), render.nice_date(today.isoformat()))
            render.EDITIONS.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(edition, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  Saved {out.relative_to(render.ROOT)} ({len(edition['tokens'])} Morning Tokens)")

    site = render.build_site()
    print(f"☕ Site ready: {site / 'index.html'}")


if __name__ == "__main__":
    main()
