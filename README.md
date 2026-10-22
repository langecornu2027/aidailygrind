# ☕ The AI Daily Grind

The AI news that matters, freshly ground every morning. In simple words.

Every morning, The AI Daily Grind:

1. **Reads the sources**: AI news sites, AI company blogs, Hacker News, Reddit,
   The AI Daily Brief podcast, AI risk sources (InsideAI, CAIS AI Safety Newsletter,
   Transformer), research papers, and new AI projects trending on GitHub
   (list in [daily_grind/sources.py](daily_grind/sources.py)).
2. **Asks Claude** to pick the 5 to 7 most important stories and write them
   in my voice ([voice.md](voice.md)). Each story is a **Morning Token**.
3. **Asks Nano Banana** (Google Gemini) to draw a cover image from Claude's scene idea.
4. **Saves** the edition in `data/editions/` and the cover in `data/covers/`.
5. **Builds the website** in `site/` and publishes it to aidailygrind.com.
   Each token also gets its own page (`YYYY-MM-DD-token-N.html`) with a social media
   preview and share buttons.

## Change things

| I want to...                    | Edit this file                                  |
| ------------------------------- | ----------------------------------------------- |
| Change my tone or topics        | [voice.md](voice.md)                            |
| Add or remove a news source     | [daily_grind/sources.py](daily_grind/sources.py)        |
| Change how Claude picks stories | `SYSTEM` in [daily_grind/write.py](daily_grind/write.py) |
| Change the cover image style    | `STYLE` in [daily_grind/cover.py](daily_grind/cover.py) |
| Change the look of the page     | [static/style.css](static/style.css), [templates/](templates/) |
| Change the time it runs         | `cron` in [.github/workflows/daily.yml](.github/workflows/daily.yml) |

## Run it on my Mac

One time only:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

See what the sources find today (free, no Claude call):

```bash
.venv/bin/python -m daily_grind --fetch-only
```

Make today's edition (reads `ANTH_KEY` and `GEMINI_KEY` from `.env`):

```bash
.venv/bin/python -m daily_grind
```

Then open `site/index.html` in your browser.

## Publishing

The site is live at **https://aidailygrind.com**. It runs on the same Google Cloud VM
as langecornu.com (`handmade-by-francois-prod`, see the langecornu README).

How a new edition gets online:

1. **GitHub Actions** runs every day at 10:30 UTC
   ([.github/workflows/daily.yml](.github/workflows/daily.yml)). It writes the edition
   and the cover, saves them in `data/`, builds the site and pushes it to the
   **`published`** branch. To run it now: **Actions → The AI Daily Grind → Run workflow**.
2. **The VM** checks the `published` branch every 15 minutes
   ([deploy/sync.sh](deploy/sync.sh), cron of user `francoisgravel`) and copies it to
   `/var/www/aidailygrind/public`. No API keys live on the VM.
3. **nginx** serves it ([deploy/nginx-aidailygrind.conf](deploy/nginx-aidailygrind.conf)),
   with a Let's Encrypt certificate from certbot (auto-renewed).

Repo secrets: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.

DNS is on Cloudflare: `A @ 136.66.67.238` and `CNAME www aidailygrind.com`, both proxied.

On the VM:

| What          | Where                                                  |
| ------------- | ------------------------------------------------------ |
| Web root      | `/var/www/aidailygrind/public`                         |
| nginx config  | `/etc/nginx/sites-available/aidailygrind`              |
| Sync script   | `/usr/local/bin/aidailygrind-sync` (log: `journalctl -t aidailygrind-sync`) |
| nginx logs    | `/var/log/nginx/aidailygrind_access.log`, `aidailygrind_error.log` |

Force a sync now:

```bash
gcloud compute ssh handmade-by-francois-prod --configuration=handmade --zone=us-west1-b --tunnel-through-iap --command=aidailygrind-sync
```

## Cost

- Claude Opus 5.5: one call per day, about $0.30.
- Nano Banana 2.1: one 1K cover per day, about $0.03.
