"""Turn saved editions (data/editions/*.json) into the static website (site/)."""

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import social

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = ROOT / "data" / "editions"
COVERS = ROOT / "data" / "covers"
SITE = ROOT / "site"
DOMAIN = "aidailygrind.com"

# Who sends the emails. The law (CASL in Canada, CAN-SPAM in the US) requires a real
# postal address in every email. A PO box is OK. Email and subscribe stay off until
# POSTAL_ADDRESS and CONTACT_EMAIL are filled in.
SENDER = "The AI Daily Grind, by François Gravel"
POSTAL_ADDRESS = "PO Box 8535 STN B, Montréal QC H3B 3J7, Canada"
CONTACT_EMAIL = "info@aidailygrind.com"
PRIVACY_OFFICER = "François Gravel"  # Québec Law 25: person in charge of personal information
POLICY_DATE = "October 22, 2026"  # change when the privacy policy changes

# Simple pages: (template, output file)
PAGES = [
    ("subscribe.html", "subscribe.html"),
    ("notice.html", "check-email.html"),
    ("notice.html", "subscribed.html"),
    ("notice.html", "unsubscribed.html"),
    ("privacy.html", "privacy.html"),
    ("disclaimer.html", "disclaimer.html"),
]

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
        cover = COVERS / f"{path.stem}.jpg"
        if cover.exists():
            # Fingerprint in the link, so a new cover is never hidden by Cloudflare's cache
            edition["cover"] = f"covers/{path.stem}.jpg?v={hashlib.sha1(cover.read_bytes()).hexdigest()[:8]}"
        words = len(edition["intro"].split()) + sum(
            len(t["summary"].split()) + len(t["why_it_matters"].split()) for t in edition["tokens"])
        edition["read_minutes"] = max(1, round(words / 200))
        if not edition.get("social_post"):  # editions written before this field existed
            lines = [f"☕ {edition['headline']}", ""]
            lines += [f"{TAG_ICONS.get(t['tag'], '▸')} {t['title']}" for t in edition["tokens"][:5]]
            lines += ["", "What do you think: are we moving too fast? 🤔"]
            edition["social_post"] = "\n".join(lines)
        edition["listen_minutes"] = max(1, round(words / 150))
        editions.append(edition)
    for number, edition in enumerate(reversed(editions), start=1):
        edition["number"] = number
    return editions


def build_site() -> Path:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.globals["tag_icons"] = TAG_ICONS
    env.globals["site_url"] = f"https://{DOMAIN}"
    # Changes when any static file changes, so Cloudflare and browsers fetch the new CSS
    env.globals["v"] = hashlib.sha1(b"".join(
        p.read_bytes() for p in sorted((ROOT / "static").rglob("*")) if p.is_file())).hexdigest()[:8]
    env.globals.update(sender=SENDER, postal_address=POSTAL_ADDRESS, contact_email=CONTACT_EMAIL,
                       privacy_officer=PRIVACY_OFFICER, policy_date=POLICY_DATE,
                       subscribe_open=bool(POSTAL_ADDRESS and CONTACT_EMAIL))
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
        edition["card"] = make_card(edition, edition["date"],
                                    f"{date.fromisoformat(edition['date']).strftime('%A, %b %-d, %Y')} · Edition #{edition['number']}",
                                    edition["headline"])
        newer = editions[i - 1] if i > 0 else None
        older = editions[i + 1] if i + 1 < len(editions) else None
        html = page.render(edition=edition, newer=newer, older=older, is_latest=(i == 0))
        (SITE / f"{edition['date']}.html").write_text(html, encoding="utf-8")
        if i == 0:
            (SITE / "index.html").write_text(html, encoding="utf-8")
        # One page per token, so each one can be shared with its own preview
        for n, token in enumerate(edition["tokens"], start=1):
            token["card"] = make_card(edition, f"{edition['date']}-token-{n}",
                                      f"Morning Token {n:02d}", token["title"], token["tag"])
            html = token_page.render(edition=edition, token=token, n=n)
            (SITE / f"{edition['date']}-token-{n}.html").write_text(html, encoding="utf-8")

    archive = env.get_template("archive.html").render(editions=editions)
    (SITE / "archive.html").write_text(archive, encoding="utf-8")

    for template, out in PAGES:
        html = env.get_template(template).render(page_name=out.removesuffix(".html"))
        (SITE / out).write_text(html, encoding="utf-8")

    build_speech(editions)
    if editions:
        build_email(env, editions[0])
    return SITE


def make_card(edition: dict, name: str, label: str, title: str, tag: str = "") -> str:
    """Share card (1200x630) for social media previews. Returns its link, with a fingerprint."""
    out = SITE / "social" / f"{name}.jpg"
    cover = COVERS / f"{edition['date']}.jpg"
    social.make_card(cover if cover.exists() else None, out, label, title, tag)
    return f"social/{name}.jpg?v={hashlib.sha1(out.read_bytes()).hexdigest()[:8]}"


def build_speech(editions: list[dict]) -> None:
    """What the AI voice reads, in short parts (about one paragraph each), so the first
    part is ready in a few seconds. "s" is the page section: 0 = headline and recap,
    1..N = Morning Token N, N+1 = le dernier mot. The VM turns a part into an MP3 only
    when a visitor first clicks Listen (deploy/mailer.py, /api/audio)."""
    out = SITE / "speech"
    out.mkdir()
    for edition in editions:
        parts = [{"s": 0, "text": f"The AI Daily Grind, {edition['date_label']}. {edition['headline']}."}]
        parts += [{"s": 0, "text": para} for para in edition["intro"].split("\n\n")]
        for n, token in enumerate(edition["tokens"], start=1):
            paras = token["summary"].split("\n\n")
            parts.append({"s": n, "text": f"Morning Token {n}. {token['title']}.\n\n{paras[0]}"})
            parts += [{"s": n, "text": para} for para in paras[1:]]
            parts.append({"s": n, "text": f"Why it matters: {token['why_it_matters']}"})
        parts.append({"s": len(edition["tokens"]) + 1, "text": f"Le dernier mot. {edition['last_word']}"})
        (out / f"{edition['date']}.json").write_text(json.dumps(parts, ensure_ascii=False), encoding="utf-8")


def build_email(env: Environment, edition: dict) -> None:
    """The email version of the newest edition. The VM mailer sends it to subscribers."""
    if not (POSTAL_ADDRESS and CONTACT_EMAIL):
        print("  (no email built: fill POSTAL_ADDRESS and CONTACT_EMAIL in render.py)")
        return
    out = SITE / "email"
    out.mkdir()
    (out / f"{edition['date']}.html").write_text(env.get_template("email.html").render(edition=edition),
                                                 encoding="utf-8")
    (out / f"{edition['date']}.txt").write_text(env.get_template("email.txt").render(edition=edition),
                                                encoding="utf-8")
    (out / f"{edition['date']}.subject").write_text(f"☕ {edition['headline']}\n", encoding="utf-8")
    meta = {"sender": SENDER, "address": POSTAL_ADDRESS, "contact": CONTACT_EMAIL}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
