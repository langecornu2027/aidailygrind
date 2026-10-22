# ☕ Café IA

Your AI news with your morning coffee, in simple words.

Every morning, Café IA:

1. **Reads the sources**: AI news sites, AI company blogs, Hacker News, Reddit,
   and research papers (list in [cafe_ia/sources.py](cafe_ia/sources.py)).
2. **Asks Claude** to pick the 5 to 7 most important stories and write them
   in my voice ([voice.md](voice.md)). Each story is a **Morning Token**.
3. **Saves** the edition in `data/editions/YYYY-MM-DD.json`.
4. **Builds the website** in `site/` and publishes it on GitHub Pages.

## Change things

| I want to...                    | Edit this file                                  |
| ------------------------------- | ----------------------------------------------- |
| Change my tone or topics        | [voice.md](voice.md)                            |
| Add or remove a news source     | [cafe_ia/sources.py](cafe_ia/sources.py)        |
| Change how Claude picks stories | `SYSTEM` in [cafe_ia/write.py](cafe_ia/write.py) |
| Change the look of the page     | [static/style.css](static/style.css), [templates/](templates/) |
| Change the time it runs         | `cron` in [.github/workflows/daily.yml](.github/workflows/daily.yml) |

## Run it on my Mac

One time only:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

See what the sources find today (free, no Claude call):

```bash
.venv/bin/python -m cafe_ia --fetch-only
```

Make today's edition (needs `ANTHROPIC_API_KEY` in your terminal):

```bash
.venv/bin/python -m cafe_ia
```

Then open `site/index.html` in your browser.

## Publish on GitHub Pages (one time setup)

1. Create a new GitHub repository (for example `cafe-ia`) and push this folder.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Name: `ANTHROPIC_API_KEY`. Value: your key from console.anthropic.com.
3. In the repo: **Settings → Pages → Source: GitHub Actions**.
4. Go to **Actions → Daily Café IA → Run workflow** to make the first edition now.

After that, it runs by itself every day at 10:30 UTC.
Your page will be at `https://<your-github-name>.github.io/cafe-ia/`.

## Cost

One Claude Opus 5.5 call per day, with about 100 stories as input.
That is roughly 25,000 to 40,000 tokens per day, so around $0.15 to $0.30 per day.
