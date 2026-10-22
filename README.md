# ☕ The AI Daily Grind

The AI news that matters, freshly ground every morning. In simple words.

Every morning, The AI Daily Grind:

1. **Reads the sources**: AI news sites, AI company blogs, Hacker News, Reddit,
   and research papers (list in [daily_grind/sources.py](daily_grind/sources.py)).
2. **Asks Claude** to pick the 5 to 7 most important stories and write them
   in my voice ([voice.md](voice.md)). Each story is a **Morning Token**.
3. **Saves** the edition in `data/editions/YYYY-MM-DD.json`.
4. **Builds the website** in `site/` and publishes it on GitHub Pages.

## Change things

| I want to...                    | Edit this file                                  |
| ------------------------------- | ----------------------------------------------- |
| Change my tone or topics        | [voice.md](voice.md)                            |
| Add or remove a news source     | [daily_grind/sources.py](daily_grind/sources.py)        |
| Change how Claude picks stories | `SYSTEM` in [daily_grind/write.py](daily_grind/write.py) |
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

Make today's edition (needs `ANTHROPIC_API_KEY` in your terminal):

```bash
.venv/bin/python -m daily_grind
```

Then open `site/index.html` in your browser.

## Publishing

The site is live at **https://aidailygrind.com**, hosted on GitHub Pages.

- The workflow runs by itself every day at 10:30 UTC.
  To run it now: **Actions → The AI Daily Grind → Run workflow**.
- It uses the repo secret `ANTHROPIC_API_KEY`.
- The domain is set in `DOMAIN` in [daily_grind/render.py](daily_grind/render.py)
  and in **Settings → Pages → Custom domain**.

DNS records at the domain registrar:

| Type  | Host  | Value                      |
| ----- | ----- | -------------------------- |
| A     | @     | 185.199.108.153            |
| A     | @     | 185.199.109.153            |
| A     | @     | 185.199.110.153            |
| A     | @     | 185.199.111.153            |
| CNAME | www   | langecornu2027.github.io   |

## Cost

One Claude Opus 5.5 call per day, with about 100 stories as input.
That is roughly 25,000 to 40,000 tokens per day, so around $0.15 to $0.30 per day.
