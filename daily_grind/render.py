"""Turn saved editions (data/editions/*.json) into the static website (site/)."""

import json
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = ROOT / "data" / "editions"
COVERS = ROOT / "data" / "covers"
SITE = ROOT / "site"
DOMAIN = "aidailygrind.com"

TAG_ICONS = {
    "Launch": "🚀", "Tool": "🛠️", "Open source": "📦", "Research": "🔬", "Business": "💼",
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
        if (COVERS / f"{path.stem}.jpg").exists():
            edition["cover"] = f"covers/{path.stem}.jpg"
        editions.append(edition)
    return editions


def build_site() -> Path:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["tag_icons"] = TAG_ICONS
    env.globals["site_url"] = f"https://{DOMAIN}"
    editions = load_editions()

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    shutil.copytree(ROOT / "static", SITE / "static")
    if COVERS.exists():
        shutil.copytree(COVERS, SITE / "covers")

    page = env.get_template("edition.html")
    token_page = env.get_template("token.html")
    for i, edition in enumerate(editions):
        newer = editions[i - 1] if i > 0 else None
        older = editions[i + 1] if i + 1 < len(editions) else None
        html = page.render(edition=edition, newer=newer, older=older, is_latest=(i == 0))
        (SITE / f"{edition['date']}.html").write_text(html, encoding="utf-8")
        if i == 0:
            (SITE / "index.html").write_text(html, encoding="utf-8")
        # One page per token, so each one can be shared with its own preview
        for n, token in enumerate(edition["tokens"], start=1):
            html = token_page.render(edition=edition, token=token, n=n)
            (SITE / f"{edition['date']}-token-{n}.html").write_text(html, encoding="utf-8")

    archive = env.get_template("archive.html").render(editions=editions)
    (SITE / "archive.html").write_text(archive, encoding="utf-8")
    return SITE
