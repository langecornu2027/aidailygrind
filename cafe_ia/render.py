"""Turn saved editions (data/editions/*.json) into the static website (site/)."""

import json
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = ROOT / "data" / "editions"
SITE = ROOT / "site"

TAG_ICONS = {
    "Launch": "🚀", "Tool": "🛠️", "Research": "🔬", "Business": "💼",
    "Policy": "⚖️", "Safety": "🛡️", "Community": "💬",
}


def nice_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%A, %B %-d, %Y")


def load_editions() -> list[dict]:
    editions = []
    for path in sorted(EDITIONS.glob("*.json"), reverse=True):
        edition = json.loads(path.read_text(encoding="utf-8"))
        edition["date"] = path.stem
        edition["date_label"] = nice_date(path.stem)
        editions.append(edition)
    return editions


def build_site() -> Path:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["tag_icons"] = TAG_ICONS
    editions = load_editions()

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    shutil.copytree(ROOT / "static", SITE / "static")

    page = env.get_template("edition.html")
    for i, edition in enumerate(editions):
        newer = editions[i - 1] if i > 0 else None
        older = editions[i + 1] if i + 1 < len(editions) else None
        html = page.render(edition=edition, newer=newer, older=older, is_latest=(i == 0))
        (SITE / f"{edition['date']}.html").write_text(html, encoding="utf-8")
        if i == 0:
            (SITE / "index.html").write_text(html, encoding="utf-8")

    archive = env.get_template("archive.html").render(editions=editions)
    (SITE / "archive.html").write_text(archive, encoding="utf-8")
    (SITE / ".nojekyll").touch()
    return SITE
