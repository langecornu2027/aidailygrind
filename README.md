# ☕ The AI Daily Grind

The AI news that matters, freshly ground every morning. In simple words.

Every morning, The AI Daily Grind:

1. **Reads the sources**: AI news sites, AI company blogs, Hacker News, Reddit,
   The AI Daily Brief podcast, AI risk sources (InsideAI, CAIS AI Safety Newsletter,
   Transformer), research papers, and new AI projects trending on GitHub
   (list in [daily_grind/sources.py](daily_grind/sources.py)).
2. **Asks the writer model** (Anthropic API) to pick the 5 to 7 most important stories and write them
   in my voice ([voice.md](voice.md)). Each story is a **Morning Token**.
3. **Asks Nano Banana** (Google Gemini) to draw a cover image from the writer's scene idea.
4. **Saves** the edition in `data/editions/` and the cover in `data/covers/`.
5. **Builds the website** in `site/` and publishes it to aidailygrind.com.
   Each token also gets its own page (`YYYY-MM-DD-token-N.html`) with a social media
   preview and share buttons.

## Change things

| I want to...                    | Edit this file                                  |
| ------------------------------- | ----------------------------------------------- |
| Change my tone or topics        | [voice.md](voice.md)                            |
| Add or remove a news source     | [daily_grind/sources.py](daily_grind/sources.py)        |
| Change how stories are picked    | `SYSTEM` in [daily_grind/write.py](daily_grind/write.py) |
| Change the cover image style    | `STYLE` in [daily_grind/cover.py](daily_grind/cover.py) |
| Change the look of the page     | [static/style.css](static/style.css), [templates/](templates/) |
| Change the time it runs         | `cron` in [.github/workflows/daily.yml](.github/workflows/daily.yml) |

## Run it on my Mac

One time only:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

See what the sources find today (free, no AI call):

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
   ([deploy/sync.sh](deploy/sync.sh), `/etc/cron.d/aidailygrind`) and copies it to
   `/var/www/aidailygrind/public`. The only key on the VM is the email token.
3. **nginx** serves it ([deploy/nginx-aidailygrind.conf](deploy/nginx-aidailygrind.conf)),
   with a Let's Encrypt certificate from certbot (auto-renewed).

Repo secrets: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`.

### Email subscriptions

- Subscribe form on every page (when `POSTAL_ADDRESS` and `CONTACT_EMAIL` are set in
  [daily_grind/render.py](daily_grind/render.py); the law needs both in every email).
- Double opt-in: the person must click a link in a confirmation email.
- Every email has an unsubscribe link and a one-click `List-Unsubscribe` header.
  Unsubscribing deletes the address.
- The service is [deploy/mailer.py](deploy/mailer.py) (Python standard library only),
  systemd unit `aidailygrind-mailer`, behind nginx at `/api/`. Subscribers are in
  SQLite at `/var/lib/aidailygrind/subscribers.db`.
- Emails go through Cloudflare Email Sending (SMTP). The token is in
  `/etc/aidailygrind/env` on the VM (`CLOUDFLARE_API_TOKEN`), and in `.env` as `EMAIL_TOKEN`.
- The sync script sends today's edition once, right after it copies the new site.
- Privacy Policy and Disclaimer: [templates/privacy.html](templates/privacy.html),
  [templates/disclaimer.html](templates/disclaimer.html). Update `POLICY_DATE` when they change.

Subscriber count:

```bash
gcloud compute ssh handmade-by-francois-prod --configuration=handmade --zone=us-west1-b --tunnel-through-iap --command="sudo -u aidailygrind python3 /opt/aidailygrind/mailer.py stats"
```

DNS is on Cloudflare: `A @ 136.66.67.238` and `CNAME www aidailygrind.com`, both proxied.

On the VM:

| What          | Where                                                  |
| ------------- | ------------------------------------------------------ |
| Web root      | `/var/www/aidailygrind/public`                         |
| nginx config  | `/etc/nginx/sites-available/aidailygrind`              |
| Sync script   | `/usr/local/bin/aidailygrind-sync`, run by `/etc/cron.d/aidailygrind` as user `aidailygrind` (logs: `journalctl -t aidailygrind-sync -t aidailygrind-mail`) |
| nginx logs    | `/var/log/nginx/aidailygrind_access.log`, `aidailygrind_error.log` |

Force a sync now:

```bash
gcloud compute ssh handmade-by-francois-prod --configuration=handmade --zone=us-west1-b --tunnel-through-iap --command=aidailygrind-sync
```

## Cost

- Writer model (Anthropic API): one call per day, about $0.30.
- Nano Banana 2.1: one 1K cover per day, about $0.03.
