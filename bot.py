import os
import json
import time
import requests
import anthropic
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
NEWS_API_KEY      = os.environ["NEWS_API_KEY"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BLUESKY_HANDLE    = os.environ["BLUESKY_HANDLE"]   # e.g. yourname.bsky.social
BLUESKY_PASSWORD  = os.environ["BLUESKY_PASSWORD"]
TELEGRAM_BOT_TOKEN= os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"] # your channel ID e.g. @yourchannel

TOPICS            = ["AI for beginners", "artificial intelligence explained", "AI tools everyday", "machine learning simple"]
ARTICLES_PER_RUN  = 3          # how many articles to post per run
POSTED_LOG        = "posted.json"  # tracks URLs already posted

# 💰 Affiliate links — added to the bottom of every post
AFFILIATES = [
    {
        "label": "🛠️ Build apps without coding:",
        "link": "https://lovable.dev/invite/6DJQO5P"
    },
    {
        "label": "🎙️ Clone your voice with AI:",
        "link": "https://try.elevenlabs.io/vj3jyo1l624v"
    },
]
# ─────────────────────────────────────────────────────────────────────────────


def load_posted() -> set:
    """Load already-posted article URLs to avoid duplicates."""
    if os.path.exists(POSTED_LOG):
        with open(POSTED_LOG) as f:
            return set(json.load(f))
    return set()


def save_posted(posted: set):
    with open(POSTED_LOG, "w") as f:
        json.dump(list(posted), f)


def fetch_articles(topic: str, posted: set) -> list:
    """Fetch fresh articles from NewsAPI, skip already-posted ones."""
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q={topic}&language=en&sortBy=publishedAt"
        f"&pageSize=10&apiKey={NEWS_API_KEY}"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    articles = resp.json().get("articles", [])

    fresh = []
    for a in articles:
        if a.get("url") not in posted and a.get("description"):
            fresh.append(a)
    return fresh


def summarize_with_claude(article: dict) -> str:
    """Use Claude to turn an article into a short, punchy social post."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are a social media writer for a page called "AI for Beginners". 
Your audience knows nothing about AI — keep it simple, friendly, and exciting.
Summarize this news into a short post. No jargon. Max 250 characters.
Add 2-3 hashtags like #AIForBeginners #ArtificialIntelligence #TechNews at the end.
Do not use quotes. Just write the post directly.

Title: {article.get('title', '')}
Description: {article.get('description', '')}"""

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


def build_post(summary: str, index: int) -> str:
    """Assemble the final post, rotating affiliate links."""
    post = summary
    if AFFILIATES:
        affiliate = AFFILIATES[index % len(AFFILIATES)]
        post += f"\n\n{affiliate['label']}\n{affiliate['link']}"
    return post




def bluesky_login() -> tuple[str, str]:
    """Log in to Bluesky and return (did, accessJwt)."""
    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_PASSWORD},
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    return data["did"], data["accessJwt"]


def post_to_bluesky(text: str, did: str, token: str):
    """Post a message to Bluesky."""
    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "repo": did,
            "collection": "app.bsky.feed.post",
            "record": {
                "text": text[:300],
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
        },
        timeout=10
    )
    resp.raise_for_status()
    print(f"  ✅ Bluesky: posted")


# ── Telegram ──────────────────────────────────────────────────────────────────

def post_to_telegram(text: str, article_url: str):
    """Send a message to a Telegram channel."""
    full_text = f"{text}\n\n🔗 {article_url}"
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": full_text,
            "disable_web_page_preview": False
        },
        timeout=10
    )
    resp.raise_for_status()
    print(f"  ✅ Telegram: posted")


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print(f"\n🤖 Bot starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    posted = load_posted()

    # Collect fresh articles across all topics
    candidates = []
    for topic in TOPICS:
        try:
            articles = fetch_articles(topic, posted)
            candidates.extend(articles)
            print(f"  📰 '{topic}': {len(articles)} new articles found")
        except Exception as e:
            print(f"  ⚠️  NewsAPI error for '{topic}': {e}")

    if not candidates:
        print("  Nothing new to post. Done.")
        return

    # Log in to Bluesky once
    try:
        did, token = bluesky_login()
        bluesky_ok = True
    except Exception as e:
        print(f"  ⚠️  Bluesky login failed: {e}")
        bluesky_ok = False

    # Process up to ARTICLES_PER_RUN articles
    count = 0
    for article in candidates:
        if count >= ARTICLES_PER_RUN:
            break

        url = article.get("url", "")
        title = article.get("title", "")
        print(f"\n  📄 Processing: {title[:60]}...")

        try:
            summary = summarize_with_claude(article)
            post_text = build_post(summary, count)
            print(f"  ✍️  Post: {post_text[:80]}...")
        except Exception as e:
            print(f"  ⚠️  Claude error: {e}")
            continue

        # Post to Bluesky
        if bluesky_ok:
            try:
                post_to_bluesky(post_text, did, token)
            except Exception as e:
                print(f"  ⚠️  Bluesky post failed: {e}")

        # Post to Telegram
        try:
            post_to_telegram(post_text, url)
        except Exception as e:
            print(f"  ⚠️  Telegram post failed: {e}")

        posted.add(url)
        count += 1
        time.sleep(3)  # be polite to APIs

    save_posted(posted)
    print(f"\n✅ Done — posted {count} article(s)")


if __name__ == "__main__":
    run()
