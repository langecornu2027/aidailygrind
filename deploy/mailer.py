#!/usr/bin/env python3
"""Email subscriptions and the AI voice for The AI Daily Grind.
Runs on the VM, Python standard library only (plus ffmpeg for MP3).

    mailer.py serve              small web API behind nginx at /api/ (systemd service)
    mailer.py send-latest        email today's edition to confirmed subscribers (run by sync)
    mailer.py stats              how many subscribers

Settings come from the environment (/etc/aidailygrind/env on the VM):
    CLOUDFLARE_API_TOKEN   token for Cloudflare Email Sending (SMTP)
    MAIL_FROM              sender, default "The AI Daily Grind <welcome@aidailygrind.com>"
    REPLY_TO               where replies go, default info@aidailygrind.com
    DB_PATH                default /var/lib/aidailygrind/subscribers.db
    WEB_ROOT               default /var/www/aidailygrind/public
    GEMINI_API_KEY         Google Gemini key for the AI voice (text-to-speech)
    AUDIO_DIR              default /var/www/aidailygrind/audio (served by nginx at /audio/)
    STATS_TOKEN            secret in the private stats link: /api/stats?key=STATS_TOKEN
"""

import base64
import hashlib
import html
import json
import os
import re
import secrets
import smtplib
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

SITE = "https://aidailygrind.com"
SMTP_HOST, SMTP_PORT = "smtp.mx.cloudflare.net", 465
MAIL_FROM = os.environ.get("MAIL_FROM", "The AI Daily Grind <welcome@aidailygrind.com>")
REPLY_TO = os.environ.get("REPLY_TO", "info@aidailygrind.com")
DB_PATH = os.environ.get("DB_PATH", "/var/lib/aidailygrind/subscribers.db")
WEB_ROOT = Path(os.environ.get("WEB_ROOT", "/var/www/aidailygrind/public"))
TIMEZONE = ZoneInfo("America/Toronto")

CONSENT_TEXT = "I want to receive The AI Daily Grind by email. I can unsubscribe at any time."
EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}$")
PENDING_DAYS = 7  # unconfirmed sign-ups are deleted after this
RATE_LIMIT = 5  # subscribe requests per IP per hour

# AI voice: an MP3 per part is made the first time someone clicks Listen, then reused
AUDIO_DIR = Path(os.environ.get("AUDIO_DIR", "/var/www/aidailygrind/audio"))
TTS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
TTS_MODEL = "gemini-3.8-flash-tts"
TTS_VOICE = "Sulafat"  # "Warm"
TTS_STYLE = ("warm, friendly morning radio host reading the news over coffee; "
             "clear, calm, natural pace, easy to understand for people who speak English as a second language")
AUDIO_MAX_AGE_DAYS = 45  # only recent editions can be voiced
AUDIO_DAILY_CAP = 150  # max parts made per day (about 5 full editions), protects the bill
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------- storage ----------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS subscribers (
            email TEXT PRIMARY KEY,
            status TEXT NOT NULL,              -- pending | confirmed
            confirm_token TEXT UNIQUE,
            unsub_token TEXT UNIQUE NOT NULL,
            consent_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            confirmed_at TEXT,
            confirm_sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS hits (      -- anonymous visit counter
            day TEXT NOT NULL,
            at INTEGER NOT NULL,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            country TEXT NOT NULL,
            visitor TEXT NOT NULL              -- daily fingerprint, see record_hit()
        );
        CREATE INDEX IF NOT EXISTS hits_day ON hits(day);
        CREATE TABLE IF NOT EXISTS salts (day TEXT PRIMARY KEY, salt TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sends (
            edition TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            recipients INTEGER
        );
    """)
    return conn


def now() -> str:
    return datetime.now(TIMEZONE).isoformat(timespec="seconds")


def cleanup(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(TIMEZONE) - timedelta(days=PENDING_DAYS)).isoformat()
    conn.execute("DELETE FROM subscribers WHERE status = 'pending' AND created_at < ?", (cutoff,))


# ---------- email ----------

def site_meta() -> dict:
    """Sender name, postal address and contact, written by the site build."""
    return json.loads((WEB_ROOT / "email" / "meta.json").read_text(encoding="utf-8"))


def smtp() -> smtplib.SMTP_SSL:
    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    server.login("api_token", os.environ["CLOUDFLARE_API_TOKEN"])
    return server


def build_message(to: str, subject: str, text: str, html_body: str, unsub_url: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Reply-To"] = REPLY_TO
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="aidailygrind.com")
    if unsub_url:
        msg["List-Unsubscribe"] = f"<{unsub_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    return msg


def send_confirmation(email: str, token: str) -> None:
    meta = site_meta()
    link = f"{SITE}/api/confirm?t={token}"
    text = (
        "Bonjour!\n\n"
        "Someone (we hope you) asked to get The AI Daily Grind by email.\n"
        f"Please confirm with this link:\n\n{link}\n\n"
        "If it was not you, do nothing. We will not email you again, and we delete this "
        f"request after {PENDING_DAYS} days.\n\n"
        f"{meta['sender']}\n{meta['address']}\n{SITE}/privacy.html\n"
    )
    page = f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#2b1d14;line-height:1.6">
<p style="font-size:22px;font-weight:bold">☕ The AI Daily Grind</p>
<p>Bonjour!</p>
<p>Someone (we hope you) asked to get The AI Daily Grind by email. Please confirm:</p>
<p><a href="{html.escape(link)}" style="display:inline-block;background:#b5652b;color:#fff;padding:12px 22px;border-radius:999px;text-decoration:none;font-weight:bold">Yes, send me the Grind</a></p>
<p style="color:#7a6656;font-size:13px">If it was not you, do nothing. We will not email you again, and we delete this request after {PENDING_DAYS} days.</p>
<p style="color:#7a6656;font-size:12px">{html.escape(meta['sender'])} · {html.escape(meta['address'])} · <a href="{SITE}/privacy.html" style="color:#7a6656">Privacy</a></p>
</div>"""
    with smtp() as server:
        server.send_message(build_message(email, "Please confirm: The AI Daily Grind", text, page, None))


def send_latest() -> None:
    """Send today's edition, and on Thursdays the Café Noir editorial, once each.
    Run after each sync; does nothing for an issue already sent."""
    today = datetime.now(TIMEZONE).date().isoformat()
    for name in (today, f"editorial-{today}"):
        send_issue(name)


def send_issue(name: str) -> None:
    html_file = WEB_ROOT / "email" / f"{name}.html"
    text_file = WEB_ROOT / "email" / f"{name}.txt"
    subject_file = WEB_ROOT / "email" / f"{name}.subject"
    if not html_file.exists():
        return
    today = name  # the key in the sends table
    conn = db()
    with conn:
        if conn.execute("SELECT 1 FROM sends WHERE edition = ?", (today,)).fetchone():
            return
        conn.execute("INSERT INTO sends (edition, started_at) VALUES (?, ?)", (today, now()))
        cleanup(conn)
    people = conn.execute("SELECT email, unsub_token FROM subscribers WHERE status = 'confirmed'").fetchall()
    html_body = html_file.read_text(encoding="utf-8")
    text = text_file.read_text(encoding="utf-8")
    subject = subject_file.read_text(encoding="utf-8").strip()

    sent = 0
    server = smtp()
    try:
        for person in people:
            unsub = f"{SITE}/api/unsubscribe?t={person['unsub_token']}"
            msg = build_message(person["email"], subject,
                                text.replace("{{UNSUBSCRIBE_URL}}", unsub),
                                html_body.replace("{{UNSUBSCRIBE_URL}}", html.escape(unsub)), unsub)
            try:
                server.send_message(msg)
                sent += 1
            except smtplib.SMTPServerDisconnected:
                server = smtp()
                server.send_message(msg)
                sent += 1
            except smtplib.SMTPRecipientsRefused as exc:
                print(f"refused {person['email']}: {exc}", file=sys.stderr)
            time.sleep(0.2)
    finally:
        server.quit()
    with conn:
        conn.execute("UPDATE sends SET finished_at = ?, recipients = ? WHERE edition = ?", (now(), sent, today))
    print(f"sent {today} to {sent} subscribers")


# ---------- AI voice ----------

audio_lock = threading.Lock()
audio_jobs: dict[str, str] = {}  # "date-NN" -> "working" | "failed"
audio_failed_at: dict[str, float] = {}
audio_made: dict[str, int] = {}  # day -> parts made today
audio_pool = ThreadPoolExecutor(max_workers=2)


def speech_parts(day: str) -> list[dict] | None:
    path = WEB_ROOT / "speech" / f"{day}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def part_name(day: str, n: int, text: str) -> str:
    """The text's fingerprint is in the name: a rewritten edition gets new files,
    never an old copy from Cloudflare's cache."""
    return f"{day}-{n:02d}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"


def tts_wav(text: str) -> bytes:
    body = {
        "model": TTS_MODEL,
        "input": [{"type": "user_input", "content": [{
            "type": "text", "text": text,
            "annotations": [{"type": "speech_metadata", "style": TTS_STYLE}],
        }]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": TTS_VOICE}]},
    }
    req = urllib.request.Request(TTS_URL, data=json.dumps(body).encode(), headers={
        "x-goog-api-key": os.environ["GEMINI_API_KEY"], "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.load(resp)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 503) or attempt == 5:
                raise
            # Google asks us to slow down: wait, then try again
            wait = int(exc.headers.get("Retry-After") or 0) or 10 * (attempt + 1)
            time.sleep(min(wait, 60))
    for step in reversed(result.get("steps", [])):
        for block in reversed(step.get("content", [])):
            if block.get("type") == "audio" and block.get("data"):
                return base64.b64decode(block["data"])
    raise RuntimeError("no audio in the answer")


def make_part(day: str, n: int, text: str) -> None:
    name = part_name(day, n, text)
    try:
        wav = tts_wav(text)
        tmp = AUDIO_DIR / f".{name}.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "pipe:0", "-ac", "1",
                        "-codec:a", "libmp3lame", "-b:a", "48k", str(tmp)],
                       input=wav, check=True, timeout=120)
        tmp.replace(AUDIO_DIR / f"{name}.mp3")
        with audio_lock:
            audio_jobs.pop(name, None)
        print(f"audio ready {name}", file=sys.stderr)
    except Exception as exc:
        print(f"audio failed {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        with audio_lock:
            audio_jobs[name] = "failed"
            audio_failed_at[name] = time.time()


def audio_status(day: str, sections: list[int], start: bool) -> dict | None:
    """Status of each part (all, or only some page sections); with start=True, begin
    making the missing ones, first parts first."""
    texts = speech_parts(day)
    if texts is None:
        return None
    parts = [n for n, p in enumerate(texts) if not sections or p["s"] in sections]
    today = datetime.now(TIMEZONE).date().isoformat()
    out = []
    with audio_lock:
        for n in parts:
            name = part_name(day, n, texts[n]["text"])
            if (AUDIO_DIR / f"{name}.mp3").exists():
                out.append({"n": n, "s": texts[n]["s"], "status": "ready", "url": f"/audio/{name}.mp3"})
                continue
            state = audio_jobs.get(name, "idle")
            if state == "failed" and time.time() - audio_failed_at.get(name, 0) > 600:
                state = "idle"  # try again after 10 minutes
            if start and state == "idle":
                if audio_made.get(today, 0) >= AUDIO_DAILY_CAP:
                    state = "failed"
                else:
                    audio_made[today] = audio_made.get(today, 0) + 1
                    audio_jobs[name] = state = "working"
                    audio_pool.submit(make_part, day, n, texts[n]["text"])
            out.append({"n": n, "s": texts[n]["s"], "status": state, "url": None})
    return {"date": day, "total": len(texts), "parts": out}


# ---------- anonymous visit counter ----------
# No cookies and no IP address is stored. A visitor is a fingerprint of IP + browser
# + a random salt that changes every day; old salts are deleted, so a fingerprint can
# never be linked back to a person or to another day. Only the day, the page, the
# country (from Cloudflare) and that fingerprint are kept.

BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|monitor|curl|wget|python|headless|lighthouse", re.I)
PATH_RE = re.compile(r"^/(?:[A-Za-z0-9_\-]+\.html)?$")  # "/" or one site page, nothing else
KINDS = {"edition", "token", "page", "subscribe", "subscribed", "check-email", "unsubscribed",
         "privacy", "disclaimer"}
HIT_KEEP_DAYS = 400


def daily_salt(conn: sqlite3.Connection, day: str) -> str:
    row = conn.execute("SELECT salt FROM salts WHERE day = ?", (day,)).fetchone()
    if row:
        return row["salt"]
    salt = secrets.token_hex(16)
    conn.execute("DELETE FROM salts WHERE day <> ?", (day,))  # forget older salts for good
    conn.execute("INSERT INTO salts (day, salt) VALUES (?, ?)", (day, salt))
    cutoff = (datetime.now(TIMEZONE).date() - timedelta(days=HIT_KEEP_DAYS)).isoformat()
    conn.execute("DELETE FROM hits WHERE day < ?", (cutoff,))
    return salt


def record_hit(ip: str, agent: str, country: str, path: str, kind: str) -> None:
    if not ip or BOT_RE.search(agent or "") or not PATH_RE.match(path or ""):
        return
    kind = kind if kind in KINDS else "page"
    country = country.upper() if re.fullmatch(r"[A-Za-z]{2}", country or "") else "XX"
    if country in ("XX", "T1"):
        country = "??"
    now_ts = int(time.time())
    day = datetime.now(TIMEZONE).date().isoformat()
    conn = db()
    with conn:
        salt = daily_salt(conn, day)
        visitor = hashlib.sha256(f"{salt}|{ip}|{agent}".encode()).hexdigest()[:16]
        recent = conn.execute("SELECT 1 FROM hits WHERE day = ? AND visitor = ? AND path = ? AND at > ?",
                              (day, visitor, path, now_ts - 1800)).fetchone()
        if not recent:  # a refresh within 30 minutes is the same view
            conn.execute("INSERT INTO hits (day, at, path, kind, country, visitor) VALUES (?, ?, ?, ?, ?, ?)",
                         (day, now_ts, path, kind, country, visitor))


def flag(code: str) -> str:
    if len(code) != 2 or not code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


COUNTRY_NAMES = {
    "CA": "Canada", "US": "United States", "FR": "France", "BE": "Belgium", "CH": "Switzerland",
    "GB": "United Kingdom", "DE": "Germany", "ES": "Spain", "IT": "Italy", "NL": "Netherlands",
    "PT": "Portugal", "IE": "Ireland", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "PL": "Poland", "AT": "Austria", "IN": "India", "CN": "China", "JP": "Japan", "KR": "South Korea",
    "SG": "Singapore", "AU": "Australia", "NZ": "New Zealand", "BR": "Brazil", "MX": "Mexico",
    "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia",
    "SN": "Senegal", "CI": "Côte d'Ivoire", "NG": "Nigeria", "ZA": "South Africa", "EG": "Egypt",
    "IL": "Israel", "AE": "United Arab Emirates", "SA": "Saudi Arabia", "TR": "Türkiye", "RU": "Russia",
    "UA": "Ukraine", "HK": "Hong Kong", "TW": "Taiwan", "VN": "Vietnam", "TH": "Thailand",
    "PH": "Philippines", "ID": "Indonesia", "MY": "Malaysia", "PK": "Pakistan", "BD": "Bangladesh",
    "HT": "Haiti", "LU": "Luxembourg", "RO": "Romania", "CZ": "Czechia", "GR": "Greece", "HU": "Hungary",
}

_titles: dict[str, str] = {}


def page_title(path: str) -> str:
    if path not in _titles:
        file = (WEB_ROOT / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        title = path
        if WEB_ROOT.resolve() not in file.parents:
            _titles[path] = title
            return title
        try:
            m = re.search(r"<title>(.*?)</title>", file.read_text(encoding="utf-8")[:3000], re.S)
            if m:
                title = html.unescape(m.group(1)).replace(" · The AI Daily Grind", "").strip()
        except OSError:
            pass
        _titles[path] = title
    return _titles[path]


def stats_html(days: int) -> str:
    conn = db()
    today = datetime.now(TIMEZONE).date()
    since = (today - timedelta(days=days - 1)).isoformat()

    def one(sql, *args):
        return conn.execute(sql, args).fetchone()[0] or 0

    def summary(start):
        return (one("SELECT COUNT(*) FROM hits WHERE day >= ?", start),
                one("SELECT COUNT(DISTINCT day || visitor) FROM hits WHERE day >= ?", start))

    cards = [("Today", summary(today.isoformat())),
             ("Last 7 days", summary((today - timedelta(days=6)).isoformat())),
             (f"Last {days} days", summary(since))]
    by_day = conn.execute("SELECT day, COUNT(*), COUNT(DISTINCT visitor) FROM hits WHERE day >= ? "
                          "GROUP BY day ORDER BY day", (since,)).fetchall()
    by_country = conn.execute("SELECT country, COUNT(DISTINCT day || visitor) v, COUNT(*) FROM hits "
                              "WHERE day >= ? GROUP BY country ORDER BY v DESC", (since,)).fetchall()
    by_page = conn.execute("SELECT path, COUNT(*) n, COUNT(DISTINCT day || visitor) FROM hits WHERE day >= ? "
                           "GROUP BY path ORDER BY n DESC LIMIT 15", (since,)).fetchall()
    by_kind = conn.execute("SELECT kind, COUNT(*) n FROM hits WHERE day >= ? GROUP BY kind ORDER BY n DESC",
                           (since,)).fetchall()

    def bar_rows(rows, label, value, extra=None):
        if not rows:
            return '<p class="empty">No visits yet.</p>'
        top = max(value(r) for r in rows) or 1
        out = []
        for r in rows:
            out.append(f'<div class="row"><span class="lbl">{label(r)}</span>'
                       f'<span class="bar"><i style="width:{max(2, value(r) * 100 // top)}%"></i></span>'
                       f'<span class="num">{value(r):,}{extra(r) if extra else ""}</span></div>')
        return "".join(out)

    def country_label(r):
        return f"{flag(r[0])} {html.escape(COUNTRY_NAMES.get(r[0], r[0]))}"

    total_visitors = sum(r[1] for r in by_country) or 1
    cards_html = "".join(f'<div class="card"><div class="k">{name}</div><div class="v">{v:,}</div>'
                         f'<div class="s">{n:,} views</div></div>' for name, (n, v) in cards)
    links = " · ".join(f'<a href="?key={html.escape(os.environ.get("STATS_TOKEN", ""))}&days={d}">{d} days</a>'
                       for d in (7, 30, 90, 365))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Visits · The AI Daily Grind</title>
<style>
body{{margin:0;background:#07090c;color:#e9eef4;font:15px/1.5 -apple-system,system-ui,sans-serif}}
main{{max-width:900px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#5eead4;margin:28px 0 10px}}
.sub{{color:#8592a0;font-size:13px}} a{{color:#ffb454}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:16px}}
.card{{background:#0e1217;border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:14px}}
.k{{color:#8592a0;font-size:12px;text-transform:uppercase}} .v{{font-size:30px;font-weight:700}} .s{{color:#8592a0;font-size:12px}}
.row{{display:grid;grid-template-columns:minmax(0,1.4fr) 1fr auto;gap:10px;align-items:center;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05)}}
.lbl{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}} .num{{font-variant-numeric:tabular-nums;color:#c3ccd6;text-align:right}}
.bar{{background:rgba(255,255,255,.05);border-radius:6px;height:10px}} .bar i{{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#ff8a3d,#ffb454)}}
.empty{{color:#8592a0}} .note{{color:#8592a0;font-size:12px;margin-top:28px}}
</style></head><body><main>
<h1>☕ Visits</h1>
<div class="sub">The AI Daily Grind · private counter · all visitors, with or without cookies · {links}</div>
<div class="cards">{cards_html}</div>
<h2>Visitors by country · last {days} days</h2>
{bar_rows(by_country, country_label, lambda r: r[1], lambda r: f' <span class="sub">({r[1] * 100 // total_visitors}%)</span>')}
<h2>Visitors per day</h2>
{bar_rows(by_day, lambda r: date.fromisoformat(r[0]).strftime("%a %b %-d"), lambda r: r[2], lambda r: f' <span class="sub">· {r[1]:,} views</span>')}
<h2>Top pages (views)</h2>
{bar_rows(by_page, lambda r: html.escape(page_title(r[0])), lambda r: r[1])}
<h2>Kind of page (views)</h2>
{bar_rows(by_kind, lambda r: html.escape(r[0]), lambda r: r[1])}
<p class="note">Anonymous: no cookies and no IP addresses are kept. A visitor is counted once per day
(a daily fingerprint that is erased the next day). Bots are ignored. Times are Montréal time.</p>
</main></body></html>"""


# ---------- web API ----------

hits: dict[str, list[float]] = {}


def rate_limited(ip: str) -> bool:
    cutoff = time.time() - 3600
    recent = [t for t in hits.get(ip, []) if t > cutoff]
    recent.append(time.time())
    hits[ip] = recent
    return len(recent) > RATE_LIMIT


UNSUB_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Unsubscribe · The AI Daily Grind</title>
<link rel="stylesheet" href="/static/style.css"></head><body><main>
<section class="edition-head" style="text-align:center"><h1>Unsubscribe?</h1>
<p>Click the button and we stop sending you The AI Daily Grind. We also delete your email.</p>
<form method="post"><button class="button" type="submit">Yes, unsubscribe me</button></form>
<p><a href="/">← Back to the site</a></p></section></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "AIDailyGrind"

    def log_message(self, fmt, *args):  # no IPs or emails in logs
        sys.stderr.write("%s %s\n" % (self.command, urlparse(self.path).path))

    def redirect(self, where: str) -> None:
        self.send_response(303)
        self.send_header("Location", where)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def token(self) -> str:
        return parse_qs(urlparse(self.path).query).get("t", [""])[0][:100]

    def send_json(self, data: dict | None) -> None:
        if data is None:
            return self.send_error(404)
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def audio(self, start: bool) -> None:
        query = parse_qs(urlparse(self.path).query)
        day = query.get("date", [""])[0]
        if not DATE_RE.match(day) or not os.environ.get("GEMINI_API_KEY"):
            return self.send_error(404)
        age = (datetime.now(TIMEZONE).date() - date.fromisoformat(day)).days
        if not 0 <= age <= AUDIO_MAX_AGE_DAYS:
            return self.send_error(404)
        sections = [int(n) for n in query.get("section", []) if n.isdigit()][:20]
        self.send_json(audio_status(day, sections, start))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/audio":
            return self.audio(start=False)
        if path == "/api/stats":
            query = parse_qs(urlparse(self.path).query)
            token = os.environ.get("STATS_TOKEN", "")
            if not token or not secrets.compare_digest(query.get("key", [""])[0], token):
                return self.send_error(404)
            days = query.get("days", ["30"])[0]
            body = stats_html(int(days) if days.isdigit() and 1 <= int(days) <= 400 else 30).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        if path == "/api/confirm":
            conn = db()
            with conn:
                row = conn.execute("SELECT email FROM subscribers WHERE confirm_token = ?",
                                   (self.token(),)).fetchone()
                if not row:
                    return self.redirect("/subscribe.html?link=expired")
                conn.execute("UPDATE subscribers SET status = 'confirmed', confirmed_at = ?, "
                             "confirm_token = NULL WHERE email = ?", (now(), row["email"]))
            return self.redirect("/subscribed.html")
        if path == "/api/unsubscribe":
            body = UNSUB_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        self.rfile_body = self.rfile.read(length).decode("utf-8", "replace")
        form = parse_qs(self.rfile_body)

        if path == "/api/audio":
            return self.audio(start=True)

        if path == "/api/hit":  # anonymous counter, sent by static/count.js
            try:
                data = json.loads(self.rfile_body) if self.rfile_body else {}
            except ValueError:
                data = {}
            record_hit(self.headers.get("X-Real-IP", ""), self.headers.get("User-Agent", ""),
                       self.headers.get("X-Country", ""), str(data.get("p", ""))[:160], str(data.get("k", ""))[:20])
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        if path == "/api/unsubscribe":  # button on the page, or one-click from the mail app
            conn = db()
            with conn:
                conn.execute("DELETE FROM subscribers WHERE unsub_token = ?", (self.token(),))
            return self.redirect("/unsubscribed.html")

        if path == "/api/subscribe":
            ip = self.headers.get("X-Real-IP", "")
            email = form.get("email", [""])[0].strip().lower()
            if form.get("website", [""])[0]:  # hidden field: only bots fill it
                return self.redirect("/check-email.html")
            if rate_limited(ip):
                return self.redirect("/subscribe.html?error=busy")
            if not EMAIL_RE.match(email) or form.get("consent", [""])[0] != "yes":
                return self.redirect("/subscribe.html?error=invalid")
            conn = db()
            with conn:
                cleanup(conn)
                row = conn.execute("SELECT * FROM subscribers WHERE email = ?", (email,)).fetchone()
                if row and row["status"] == "confirmed":
                    return self.redirect("/check-email.html")  # never reveal who is subscribed
                recently = row and row["confirm_sent_at"] and \
                    datetime.fromisoformat(row["confirm_sent_at"]) > datetime.now(TIMEZONE) - timedelta(hours=1)
                if recently:
                    return self.redirect("/check-email.html")
                token = secrets.token_urlsafe(24)
                if row:
                    conn.execute("UPDATE subscribers SET confirm_token = ?, confirm_sent_at = ? WHERE email = ?",
                                 (token, now(), email))
                else:
                    conn.execute(
                        "INSERT INTO subscribers (email, status, confirm_token, unsub_token, consent_text, "
                        "created_at, confirm_sent_at) VALUES (?, 'pending', ?, ?, ?, ?, ?)",
                        (email, token, secrets.token_urlsafe(24), CONSENT_TEXT, now(), now()))
            try:
                send_confirmation(email, token)
            except Exception as exc:
                print(f"confirmation email failed: {type(exc).__name__}", file=sys.stderr)
                return self.redirect("/subscribe.html?error=mail")
            return self.redirect("/check-email.html")

        self.send_error(404)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "serve":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 8787
        db().close()
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    elif command == "send-latest":
        send_latest()
    elif command == "stats":
        conn = db()
        for status, count in conn.execute("SELECT status, COUNT(*) FROM subscribers GROUP BY status"):
            print(f"{status}: {count}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
