"""The list of places The AI Daily Grind reads every morning.

To add a source, copy a line and change the name and URL.
To remove one, delete its line (or put a # in front).
"""

# RSS / Atom feeds: (name, kind, url)
FEEDS = [
    # News sites
    ("The Verge", "news", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("TechCrunch", "news", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat", "news", "https://venturebeat.com/category/ai/feed/"),
    ("MIT Technology Review", "news", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("Ars Technica", "news", "https://arstechnica.com/ai/feed/"),
    # AI company blogs
    ("OpenAI", "company", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "company", "https://deepmind.google/blog/rss.xml"),
    ("Google AI", "company", "https://blog.google/technology/ai/rss/"),
    ("Hugging Face", "company", "https://huggingface.co/blog/feed.xml"),
    # Community buzz
    ("Simon Willison", "community", "https://simonwillison.net/atom/everything/"),
    ("r/LocalLLaMA", "community", "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"),
    ("r/artificial", "community", "https://www.reddit.com/r/artificial/top/.rss?t=day"),
    # Research
    ("arXiv cs.AI", "research", "https://rss.arxiv.org/rss/cs.AI"),
]

# Hacker News: only stories with at least this many points
HN_MIN_POINTS = 60

# Hugging Face daily papers: only papers with at least this many upvotes
HF_MIN_UPVOTES = 10

# Max items kept from one source (keeps busy feeds like arXiv from taking over)
MAX_PER_SOURCE = 15

# Only keep items published in the last N hours
LOOKBACK_HOURS = 30
