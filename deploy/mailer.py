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
"""

import base64
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
AUDIO_DAILY_CAP = 40  # max parts made per day (about 4 full editions), protects the bill
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
    """Send today's edition once. Run after each sync; does nothing if already sent."""
    today = datetime.now(TIMEZONE).date().isoformat()
    html_file = WEB_ROOT / "email" / f"{today}.html"
    text_file = WEB_ROOT / "email" / f"{today}.txt"
    subject_file = WEB_ROOT / "email" / f"{today}.subject"
    if not html_file.exists():
        return
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
audio_pool = ThreadPoolExecutor(max_workers=3)


def speech_parts(day: str) -> list[str] | None:
    path = WEB_ROOT / "speech" / f"{day}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def part_name(day: str, n: int) -> str:
    return f"{day}-{n:02d}"


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
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.load(resp)
    for step in reversed(result.get("steps", [])):
        for block in reversed(step.get("content", [])):
            if block.get("type") == "audio" and block.get("data"):
                return base64.b64decode(block["data"])
    raise RuntimeError("no audio in the answer")


def make_part(day: str, n: int, text: str) -> None:
    name = part_name(day, n)
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


def audio_status(day: str, parts: list[int], start: bool) -> dict | None:
    """Status of each part; with start=True, begin making the missing ones (in order)."""
    texts = speech_parts(day)
    if texts is None:
        return None
    parts = [n for n in parts if 0 <= n < len(texts)] or list(range(len(texts)))
    today = datetime.now(TIMEZONE).date().isoformat()
    out = []
    with audio_lock:
        for n in parts:
            name = part_name(day, n)
            if (AUDIO_DIR / f"{name}.mp3").exists():
                out.append({"n": n, "status": "ready", "url": f"/audio/{name}.mp3"})
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
                    audio_pool.submit(make_part, day, n, texts[n])
            out.append({"n": n, "status": state, "url": None})
    return {"date": day, "total": len(texts), "parts": out}


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
        parts = [int(n) for n in query.get("part", []) if n.isdigit()][:20]
        self.send_json(audio_status(day, parts, start))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/audio":
            return self.audio(start=False)
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
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))

        if path == "/api/audio":
            return self.audio(start=True)

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
