"""Turn saved editions (data/editions/*.json) into the static website (site/)."""

import hashlib
import json
import re
import shutil
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import social

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = ROOT / "data" / "editions"
EDITORIALS = ROOT / "data" / "editorials"  # Le Café Noir, weekly
COVERS = ROOT / "data" / "covers"
SITE = ROOT / "site"
DOMAIN = "aidailygrind.com"
SITE_URL = f"https://{DOMAIN}"
LINKEDIN_URL = "https://www.linkedin.com/company/ai-daily-grind/"  # company page 144021861
AUTHOR = "François Gravel"
# Google Search Console ownership check (HTML tag method). Keep it, or Search Console stops working.
GOOGLE_SITE_VERIFICATION = "SHvFTdzmYz2Y-8Z75A0XGGp9NsXz_N2Oh37l4-bQ_IM"
INDEXNOW_KEY = "fb8381e0f631a46988745f9fbb7309b2"  # public by design: Bing checks it at /<key>.txt
PUBLISH_TIME = "06:30"  # editions go out around this time, Montréal time

# Who sends the emails. The law (CASL in Canada, CAN-SPAM in the US) requires a real
# postal address in every email. A PO box is OK. Email and subscribe stay off until
# POSTAL_ADDRESS and CONTACT_EMAIL are filled in.
SENDER = "The AI Daily Grind, by François Gravel"
POSTAL_ADDRESS = "PO Box 8535 STN B, Montréal QC H3B 3J7, Canada"
CONTACT_EMAIL = "info@aidailygrind.com"
PRIVACY_OFFICER = "François Gravel"  # Québec Law 25: person in charge of personal information
POLICY_DATE = "October 22, 2026 (analytics added)"  # change when the privacy policy changes

# Simple pages: (template, output file)
PAGES = [
    ("subscribe.html", "subscribe.html"),
    ("notice.html", "check-email.html"),
    ("notice.html", "subscribed.html"),
    ("notice.html", "unsubscribed.html"),
    ("privacy.html", "privacy.html"),
    ("disclaimer.html", "disclaimer.html"),
    ("projects.html", "projects.html"),
    ("about.html", "about.html"),
]

TAG_ICONS = {
    "Launch": "🚀", "Tool": "🛠️", "Open source": "📦", "Research": "🔬", "Business": "💼",
    "Policy": "⚖️", "Safety": "🛡️", "Community": "💬",
}


TAG_HASHTAGS = {
    "Safety": ["#AISafety", "#Cybersecurity"], "Policy": ["#AIPolicy", "#AIRegulation"],
    "Launch": ["#GenerativeAI", "#AITools"], "Tool": ["#AITools", "#Productivity"],
    "Open source": ["#OpenSource", "#GitHub"], "Research": ["#AIResearch", "#MachineLearning"],
    "Business": ["#AIBusiness", "#FutureOfWork"], "Community": ["#AICommunity", "#TechNews"],
    "Opinion": ["#AIEthics", "#AISafety"],
}
BRAND_HASHTAG = "#AIDailyGrind"


def clean_hashtags(tags, fallback_tag: str = "") -> list[str]:
    """Up to 5 hashtags for manual shares: '#' + letters/digits, no duplicates, brand tag last."""
    tags = list(tags or []) or ["#AI"] + TAG_HASHTAGS.get(fallback_tag, [])
    out = []
    for tag in tags:
        tag = "#" + re.sub(r"[^0-9A-Za-z_]", "", str(tag).lstrip("#"))
        if len(tag) > 2 and tag.lower() not in [o.lower() for o in out] and tag.lower() != BRAND_HASHTAG.lower():
            out.append(tag)
    return out[:4] + [BRAND_HASHTAG]


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
        first_tag = edition["tokens"][0]["tag"] if edition["tokens"] else ""
        edition["hashtags"] = clean_hashtags(edition.get("hashtags") or
                                             ["#AI", "#ArtificialIntelligence"] + TAG_HASHTAGS.get(first_tag, [])[:1])
        for token in edition["tokens"]:
            token["hashtags"] = clean_hashtags(token.get("hashtags"), token["tag"])
        editions.append(edition)
    for number, edition in enumerate(reversed(editions), start=1):
        edition["number"] = number
    return editions


def week_editorial(editorials: list[dict], day: str):
    """The Café Noir published 0 to 6 days before this edition, if any."""
    d = date.fromisoformat(day)
    for piece in editorials:
        if 0 <= (d - date.fromisoformat(piece["date"])).days <= 6:
            return piece
    return None


def load_editorials() -> list[dict]:
    pieces = []
    for path in sorted(EDITORIALS.glob("*.json"), reverse=True):
        piece = json.loads(path.read_text(encoding="utf-8"))
        piece["date"] = path.stem
        piece["date_label"] = nice_date(path.stem)
        piece["slug"] = f"cafe-noir-{path.stem}"
        cover = COVERS / f"editorial-{path.stem}.jpg"
        if cover.exists():
            piece["cover"] = f"covers/editorial-{path.stem}.jpg?v={hashlib.sha1(cover.read_bytes()).hexdigest()[:8]}"
        words = len(piece["body"].split())
        piece["read_minutes"] = max(1, round(words / 200))
        piece["hashtags"] = clean_hashtags(piece.get("hashtags") or ["#AI", "#AIEthics", "#AISafety", "#FutureOfAI"])
        piece["blocks"] = [("h2", b[3:].strip()) if b.startswith("## ") else ("p", b.strip())
                           for b in piece["body"].split("\n\n") if b.strip()]
        pieces.append(piece)
    for number, piece in enumerate(reversed(pieces), start=1):
        piece["number"] = number
    return pieces


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
    env.globals["google_site_verification"] = GOOGLE_SITE_VERIFICATION
    env.globals["linkedin_url"] = LINKEDIN_URL
    env.globals["topic_slug"] = topic_slug
    env.globals.update(sender=SENDER, postal_address=POSTAL_ADDRESS, contact_email=CONTACT_EMAIL,
                       privacy_officer=PRIVACY_OFFICER, policy_date=POLICY_DATE,
                       subscribe_open=bool(POSTAL_ADDRESS and CONTACT_EMAIL))
    editions = load_editions()
    editorials = load_editorials()

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
        ld = jsonld_edition(edition)
        noir = week_editorial(editorials, edition["date"])
        html = page.render(edition=edition, newer=newer, older=older, is_latest=(i == 0), jsonld=ld, noir=noir)
        (SITE / f"{edition['date']}.html").write_text(html, encoding="utf-8")
        if i == 0:  # the home page shows the newest edition, with the site's own address and info
            html = page.render(edition=edition, newer=newer, older=older, is_latest=True, is_home=True,
                               jsonld=jsonld_home(edition), noir=noir)
            (SITE / "index.html").write_text(html, encoding="utf-8")
        # One page per token, so each one can be shared with its own preview
        for n, token in enumerate(edition["tokens"], start=1):
            token["card"] = make_card(edition, f"{edition['date']}-token-{n}",
                                      f"Morning Token {n:02d}", token["title"], token["tag"])
            html = token_page.render(edition=edition, token=token, n=n, jsonld=jsonld_token(edition, token, n))
            (SITE / f"{edition['date']}-token-{n}.html").write_text(html, encoding="utf-8")

    noir_page = env.get_template("editorial.html")
    for piece in editorials:
        piece["card"] = make_card({"date": piece["date"]}, piece["slug"], f"Le Café Noir · {piece['date_label']}",
                                  piece["title"], "Opinion", cover_name=f"editorial-{piece['date']}")
        html = noir_page.render(piece=piece, jsonld=jsonld_editorial(piece), page_name=piece["slug"])
        (SITE / f"{piece['slug']}.html").write_text(html, encoding="utf-8")
    (SITE / "cafe-noir.html").write_text(env.get_template("cafe_noir.html").render(
        pieces=editorials, page_name="cafe-noir"), encoding="utf-8")

    archive = env.get_template("archive.html").render(editions=editions, topics=sorted(topics(editions)))
    (SITE / "archive.html").write_text(archive, encoding="utf-8")

    topic_page = env.get_template("topic.html")
    all_topics = topics(editions)
    for tag, items in all_topics.items():
        html = topic_page.render(tag=tag, items=items, intro=TOPIC_INTROS.get(tag, ""), page_name=topic_slug(tag),
                                 all_tags=sorted(all_topics))
        (SITE / f"{topic_slug(tag)}.html").write_text(html, encoding="utf-8")

    for template, out in PAGES:
        html = env.get_template(template).render(page_name=out.removesuffix(".html"))
        (SITE / out).write_text(html, encoding="utf-8")

    (SITE / "404.html").write_text(env.get_template("404.html").render(page_name="404"), encoding="utf-8")
    build_seo_files(editions, editorials)
    build_speech(editions)
    if editions:
        build_email(env, editions[0])
    if editorials and editorials[0]["date"] == datetime.now(ZoneInfo("America/Toronto")).date().isoformat():
        build_editorial_email(env, editorials[0])
    return SITE


# ---------- SEO: structured data, sitemap, robots.txt, RSS ----------

def published(edition: dict) -> str:
    """Publication time as ISO 8601 with the Montréal offset (daylight time aware)."""
    d = date.fromisoformat(edition["date"])
    hh, mm = map(int, PUBLISH_TIME.split(":"))
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo("America/Toronto")).isoformat()


def short(text: str, limit: int = 155) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _ld(data) -> str:
    # Safe inside <script>: no "</" can close the tag early
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _org() -> dict:
    about = f"{SITE_URL}/about.html"
    return {"@type": "NewsMediaOrganization", "name": "The AI Daily Grind", "url": SITE_URL + "/",
            "sameAs": [LINKEDIN_URL], "foundingDate": "2026-10-22",
            "description": "A daily recap of the AI news that matters, in simple English, with a critical eye on AI risks.",
            "publishingPrinciples": f"{about}#editorial", "correctionsPolicy": f"{about}#corrections",
            "ethicsPolicy": f"{about}#ai", "actionableFeedbackPolicy": f"{about}#contact",
            "email": CONTACT_EMAIL,
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/static/logo-512.png", "width": 512, "height": 512}}


def _author() -> dict:
    return {"@type": "Person", "name": AUTHOR, "url": f"{SITE_URL}/about.html",
            "sameAs": ["https://langecornu.com/"]}


def _article(edition: dict, url: str, headline: str, description: str, card: str, section: str = "") -> dict:
    images = [f"{SITE_URL}/{card}"]
    if edition.get("cover"):
        images.append(f"{SITE_URL}/{edition['cover']}")
    article = {
        "@type": "NewsArticle", "mainEntityOfPage": url, "url": url,
        "headline": headline[:110], "description": description, "image": images,
        "datePublished": published(edition), "dateModified": published(edition),
        "author": _author(), "publisher": _org(), "inLanguage": "en", "isAccessibleForFree": True,
    }
    if section:
        article["articleSection"] = section
        article["about"] = {"@type": "Thing", "name": section}
    article["keywords"] = ["artificial intelligence", "AI news"] + ([section] if section else [])
    return article


def jsonld_edition(edition: dict) -> str:
    url = f"{SITE_URL}/{edition['date']}.html"
    return _ld({"@context": "https://schema.org", **_article(
        edition, url, edition["headline"], short(edition["intro"].split("\n\n")[0]), edition["card"])})


def jsonld_editorial(piece: dict) -> str:
    url = f"{SITE_URL}/{piece['slug']}.html"
    article = _article(piece, url, piece["title"], short(piece["dek"]), piece["card"], "Opinion")
    article["@type"] = "OpinionNewsArticle"
    article["wordCount"] = len(piece["body"].split())
    return _ld({"@context": "https://schema.org", "@graph": [article, {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "The AI Daily Grind", "item": SITE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": "Le Café Noir", "item": f"{SITE_URL}/cafe-noir.html"},
        {"@type": "ListItem", "position": 3, "name": piece["title"], "item": url},
    ]}]})


def jsonld_home(edition: dict) -> str:
    return _ld({"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "The AI Daily Grind", "alternateName": "AI Daily Grind",
         "url": SITE_URL + "/", "inLanguage": "en",
         "description": "The AI news that matters, freshly ground every morning. In simple words."},
        _org(),
        _article(edition, f"{SITE_URL}/{edition['date']}.html", edition["headline"],
                 short(edition["intro"].split("\n\n")[0]), edition["card"]),
    ]})


def jsonld_token(edition: dict, token: dict, n: int) -> str:
    url = f"{SITE_URL}/{edition['date']}-token-{n}.html"
    return _ld({"@context": "https://schema.org", "@graph": [
        _article(edition, url, token["title"], short(token.get("share_text") or token["why_it_matters"]),
                 token["card"], token["tag"]),
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "The AI Daily Grind", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": edition["date_label"],
             "item": f"{SITE_URL}/{edition['date']}.html"},
            {"@type": "ListItem", "position": 3, "name": token["title"], "item": url},
        ]},
    ]})


def topic_slug(tag: str) -> str:
    return "topic-" + tag.lower().replace(" ", "-")


def topics(editions: list[dict]) -> dict[str, list]:
    """Tag -> [(edition, n, token), ...], newest first."""
    out: dict[str, list] = {}
    for e in editions:
        for n, t in enumerate(e["tokens"], start=1):
            out.setdefault(t["tag"], []).append((e, n, t))
    return out


TOPIC_INTROS = {
    "Safety": "AI safety and risk news: jailbreaks, misuse, security holes, and the warnings worth hearing.",
    "Policy": "AI rules, laws, lobbying and politics: who decides how AI is used, and how.",
    "Launch": "New AI models, apps and features from the big labs and startups.",
    "Tool": "AI tools you can try today, explained simply.",
    "Open source": "Open-source and open-weight AI projects, often trending on GitHub.",
    "Research": "AI research papers and discoveries, in plain words.",
    "Business": "The money and power behind AI: deals, funding, jobs and big company moves.",
    "Community": "What the AI community is talking about on Hacker News, Reddit and beyond.",
}


def _rss_item(title, url, when, description, body, image, category) -> str:
    return (f"<item><title>{escape(title)}</title><link>{url}</link><guid isPermaLink=\"true\">{url}</guid>"
            f"<pubDate>{when}</pubDate><dc:creator>{escape(AUTHOR)}</dc:creator><category>{escape(category)}</category>"
            f"<description>{escape(description)}</description><content:encoded><![CDATA[{body}]]></content:encoded>"
            f'<enclosure url="{escape(image)}" type="image/jpeg" length="0"/>'
            f'<media:content url="{escape(image)}" medium="image" type="image/jpeg" width="1200" height="630"/></item>')


def build_seo_files(editions: list[dict], editorials: list[dict]) -> None:
    newest = editions[0]["date"] if editions else date.today().isoformat()
    urls = [(f"{SITE_URL}/", newest, "daily", "1.0", editions[0].get("cover") if editions else None),
            (f"{SITE_URL}/archive.html", newest, "daily", "0.6", None)]
    for e in editions:
        urls.append((f"{SITE_URL}/{e['date']}.html", e["date"], "monthly", "0.8", e.get("cover")))
        for n in range(1, len(e["tokens"]) + 1):
            urls.append((f"{SITE_URL}/{e['date']}-token-{n}.html", e["date"], "monthly", "0.7", None))
    urls.append((f"{SITE_URL}/cafe-noir.html", editorials[0]["date"] if editorials else newest, "weekly", "0.6", None))
    for piece in editorials:
        urls.append((f"{SITE_URL}/{piece['slug']}.html", piece["date"], "monthly", "0.8",
                     piece.get("cover")))
    for tag in topics(editions):
        urls.append((f"{SITE_URL}/{topic_slug(tag)}.html", newest, "daily", "0.6", None))
    for page in ("about", "subscribe", "privacy", "disclaimer", "projects"):
        urls.append((f"{SITE_URL}/{page}.html", newest, "yearly", "0.3", None))

    items = []
    for loc, lastmod, freq, prio, cover in urls:
        image = (f"<image:image><image:loc>{escape(SITE_URL + '/' + cover.split('?')[0])}</image:loc></image:image>"
                 if cover else "")
        items.append(f"<url><loc>{escape(loc)}</loc><lastmod>{lastmod}</lastmod>"
                     f"<changefreq>{freq}</changefreq><priority>{prio}</priority>{image}</url>")
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n' + "\n".join(items) + "\n</urlset>\n",
        encoding="utf-8")

    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /email/\nDisallow: /speech/\n\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\nSitemap: {SITE_URL}/news-sitemap.xml\n", encoding="utf-8")

    # Google News sitemap: only articles from the last 2 days, as Google asks
    cutoff = datetime.now(ZoneInfo("America/Toronto")).date().toordinal() - 2
    news = []
    for e in editions:
        if date.fromisoformat(e["date"]).toordinal() < cutoff:
            continue
        pages = [(f"{SITE_URL}/{e['date']}.html", e["headline"])]
        pages += [(f"{SITE_URL}/{e['date']}-token-{n}.html", t["title"]) for n, t in enumerate(e["tokens"], start=1)]
        for loc, title in pages:
            news.append(f"<url><loc>{escape(loc)}</loc><news:news><news:publication>"
                        "<news:name>The AI Daily Grind</news:name><news:language>en</news:language>"
                        f"</news:publication><news:publication_date>{published(e)}</news:publication_date>"
                        f"<news:title>{escape(title)}</news:title></news:news></url>")
    for piece in editorials:
        if date.fromisoformat(piece["date"]).toordinal() >= cutoff:
            news.append(f"<url><loc>{SITE_URL}/{piece['slug']}.html</loc><news:news><news:publication>"
                        "<news:name>The AI Daily Grind</news:name><news:language>en</news:language>"
                        f"</news:publication><news:publication_date>{published(piece)}</news:publication_date>"
                        f"<news:title>{escape(piece['title'])}</news:title></news:news></url>")
    (SITE / "news-sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n' + "\n".join(news) + "\n</urlset>\n",
        encoding="utf-8")

    # IndexNow (Bing, DuckDuckGo, Yandex...): the VM sends this right after a new edition goes live
    (SITE / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY, encoding="utf-8")
    if editions:
        e = editions[0]
        fresh = [f"{SITE_URL}/", f"{SITE_URL}/{e['date']}.html", f"{SITE_URL}/archive.html"]
        fresh += [f"{SITE_URL}/{e['date']}-token-{n}.html" for n in range(1, len(e["tokens"]) + 1)]
        fresh += [f"{SITE_URL}/{topic_slug(t['tag'])}.html" for t in e["tokens"]]
        if editorials and editorials[0]["date"] == e["date"]:
            fresh += [f"{SITE_URL}/{editorials[0]['slug']}.html", f"{SITE_URL}/cafe-noir.html"]
        (SITE / "indexnow.json").write_text(json.dumps({
            "host": DOMAIN, "key": INDEXNOW_KEY, "keyLocation": f"{SITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": list(dict.fromkeys(fresh))}), encoding="utf-8")

    # Main RSS feed, for readers and news aggregators: one item per Morning Token, plus the edition
    entries = []
    for e in editions[:15]:
        when = format_datetime(datetime.fromisoformat(published(e)).astimezone(timezone.utc))
        url = f"{SITE_URL}/{e['date']}.html"
        body = "".join(f"<p>{escape(p)}</p>" for p in e["intro"].split("\n\n"))
        body += "<ul>" + "".join(
            f'<li><a href="{SITE_URL}/{e["date"]}-token-{n}.html">{escape(t["title"])}</a></li>'
            for n, t in enumerate(e["tokens"], start=1)) + "</ul>"
        entries.append(_rss_item(e["headline"], url, when, short(e["intro"].split("\n\n")[0], 300), body,
                                 f"{SITE_URL}/{e['card']}", "Daily edition"))
        for n, tok in enumerate(e["tokens"], start=1):
            turl = f"{SITE_URL}/{e['date']}-token-{n}.html"
            tbody = "".join(f"<p>{escape(p)}</p>" for p in tok["summary"].split("\n\n"))
            tbody += f"<p><strong>Why it matters:</strong> {escape(tok['why_it_matters'])}</p>"
            tbody += "<p>Sources: " + ", ".join(
                f'<a href="{escape(s["url"])}">{escape(s["name"])}</a>' for s in tok.get("sources", [])) + "</p>"
            entries.append(_rss_item(tok["title"], turl, when, short(tok["summary"].split("\n\n")[0], 300),
                                     tbody, f"{SITE_URL}/{tok['card']}", tok["tag"]))
    for piece in editorials[:10]:
        when = format_datetime(datetime.fromisoformat(published(piece)).astimezone(timezone.utc))
        body = "".join(f"<h2>{escape(x)}</h2>" if kind == "h2" else f"<p>{escape(x)}</p>" for kind, x in piece["blocks"])
        body += f"<p><strong>{escape(piece['call_to_action'])}</strong></p><p><em>{escape(piece['question'])}</em></p>"
        entries.append(_rss_item(piece["title"], f"{SITE_URL}/{piece['slug']}.html", when, piece["dek"], body,
                                 f"{SITE_URL}/{piece['card']}", "Le Café Noir (opinion)"))
    (SITE / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>The AI Daily Grind</title><link>{SITE_URL}/</link>"
        "<description>The AI news that matters, freshly ground every morning. In simple words, "
        "with a critical eye on AI risks.</description>"
        f'<language>en</language><atom:link href="{SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>'
        f"<copyright>The AI Daily Grind</copyright><category>Artificial Intelligence</category><ttl>60</ttl>"
        f"<image><url>{SITE_URL}/static/logo-512.png</url><title>The AI Daily Grind</title><link>{SITE_URL}/</link></image>"
        + "".join(entries) + "</channel></rss>\n", encoding="utf-8")

    # Feed for the daily LinkedIn page post (Zapier / Make read it): one item per edition,
    # with the ready-made post text, the share card and a tagged link
    li = []
    for piece in editorials[:4]:  # Thursdays: the editorial is posted too
        url = f"{SITE_URL}/{piece['slug']}.html"
        tagged = f"{url}?utm_source=linkedin&utm_medium=social&utm_campaign=page_autopost"
        text = f"🖤☕ LE CAFÉ NOIR, my weekly take\n\n{piece['social_post']}\n\n👉 Read it: {tagged}"
        card = f"{SITE_URL}/{piece['card']}"
        when = format_datetime(datetime.fromisoformat(published(piece)).astimezone(timezone.utc))
        li.append(f"<item><title>{escape(piece['title'])}</title><link>{escape(tagged)}</link>"
                  f"<guid isPermaLink=\"false\">aidailygrind-cafe-noir-{piece['date']}</guid><pubDate>{when}</pubDate>"
                  f"<description>{escape(text)}</description>"
                  f'<enclosure url="{escape(card)}" type="image/jpeg" length="0"/>'
                  f'<media:content url="{escape(card)}" medium="image" type="image/jpeg" width="1200" height="630"/>'
                  "</item>")
    for e in editions[:10]:
        url = f"{SITE_URL}/{e['date']}.html"
        tagged = f"{url}?utm_source=linkedin&utm_medium=social&utm_campaign=page_autopost"
        text = f"{e.get('social_post') or e['headline']}\n\n👉 Read or listen: {tagged}"
        card = f"{SITE_URL}/{e['card']}"
        when = format_datetime(datetime.fromisoformat(published(e)).astimezone(timezone.utc))
        li.append(f"<item><title>{escape(e['headline'])}</title><link>{escape(tagged)}</link>"
                  f"<guid isPermaLink=\"false\">aidailygrind-{e['date']}</guid><pubDate>{when}</pubDate>"
                  f"<description>{escape(text)}</description>"
                  f'<enclosure url="{escape(card)}" type="image/jpeg" length="0"/>'
                  f'<media:content url="{escape(card)}" medium="image" type="image/jpeg" width="1200" height="630"/>'
                  "</item>")
    (SITE / "linkedin.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>'
        f"<title>The AI Daily Grind · LinkedIn posts</title><link>{SITE_URL}/</link>"
        "<description>One ready-to-post LinkedIn update per edition.</description><language>en</language>"
        + "".join(li) + "</channel></rss>\n", encoding="utf-8")


def make_card(edition: dict, name: str, label: str, title: str, tag: str = "", cover_name: str = "") -> str:
    """Share card (1200x630) for social media previews. Returns its link, with a fingerprint."""
    out = SITE / "social" / f"{name}.jpg"
    cover = COVERS / f"{cover_name or edition['date']}.jpg"
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


def build_editorial_email(env: Environment, piece: dict) -> None:
    """Thursday: the editorial email. The VM mailer sends it once, next to the daily edition."""
    if not (POSTAL_ADDRESS and CONTACT_EMAIL):
        return
    out = SITE / "email"
    out.mkdir(exist_ok=True)
    name = f"editorial-{piece['date']}"
    (out / f"{name}.html").write_text(env.get_template("email_editorial.html").render(piece=piece), encoding="utf-8")
    (out / f"{name}.txt").write_text(env.get_template("email_editorial.txt").render(piece=piece), encoding="utf-8")
    (out / f"{name}.subject").write_text(f"🖤☕ Le Café Noir: {piece['title']}\n", encoding="utf-8")


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
