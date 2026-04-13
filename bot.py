import os
import json
import time
import requests
import anthropic
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
NEWS_API_KEY       = os.environ["NEWS_API_KEY"]
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
BLUESKY_HANDLE     = os.environ["BLUESKY_HANDLE"]   # e.g. yourname.bsky.social
BLUESKY_PASSWORD   = os.environ["BLUESKY_PASSWORD"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"] # e.g. @yourchannel

TOPICS             = [
    "AI for beginners",
    "artificial intelligence explained",
    "AI tools everyday",
    "machine learning simple"
]
ARTICLES_PER_RUN   = 1
POSTED_LOG         = "posted.json"

CTA                = "\n\n👉 Want simple AI tools? Check my profile"
MAX_POST_LENGTH    = 300

# ──────────────────────────────────────────────────────────────────────────────


def load_posted() -> set:
    """Load already-posted article URLs to avoid duplicates."""
    if os.path.exists(POSTED_LOG):
        with open(POSTED_LOG, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_posted(posted: set):
    """Save posted article URLs."""
    with open(POSTED_LOG, "w", encoding="utf-8") as f:
        json.dump(list(posted), f)


def fetch_articles(topic: str, posted: set) -> list:
    """Fetch fresh articles from NewsAPI and skip already-posted ones."""
    url = (
        "https://newsapi.org/v2/everything"
        f"?q={topic}&language=en&sortBy=publishedAt"
        f"&pageSize=10&apiKey={NEWS_API_KEY}"
    )
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    articles = resp.json().get("articles", [])

    fresh = []
    for article in articles:
        if article.get("url") not in posted and article.get("description"):
            fresh.append(article)

    return fresh


def summarize_with_claude(article: dict) -> str:
    """Turn an article into a short beginner-friendly social post."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are a social media writer for a page called "AI for Beginners".

Your audience knows nothing about AI. Keep it simple, clear, useful, and interesting.

Write a short post with:
- 1 to 2 simple sentences
- beginner-friendly language
- no jargon
- a curiosity-driven tone
- maximum 200 characters
- 2 to 3 relevant hashtags at the end, such as #AIForBeginners #TechNews

Rules:
- Do NOT include any links
- Do NOT include any call to action
- Do NOT use quotation marks
- Output only the post text

Title: {article.get('title', '')}
Description: {article.get('description', '')}
"""

    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )

    return msg.content[0].text.strip()


def build_post(summary: str) -> str:
    """Append standard CTA and make sure it fits Bluesky length."""
    post = summary + CTA

    if len(post) > MAX_POST_LENGTH:
        allowed_summary_length = MAX_POST_LENGTH - len(CTA) - 3
        trimmed_summary = summary[:allowed_summary_length].rstrip()
        post = trimmed_summary + "..." + CTA

    return post


def bluesky_login() -> tuple[str, str]:
    """Log in to Bluesky and return (did, accessJwt)."""
    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": BLUESKY_HANDLE, "password": BLUESKY_PASSWORD},
        timeout=10,
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
                "text": text[:MAX_POST_LENGTH],
                "createdAt": datetime.now(timezone.utc).isoformat(),
            },
        },
        timeout=10,
    )
    resp.raise_for_status()
    print("  ✅ Bluesky: posted")


def post_to_telegram(text: str, article_url: str):
    """Send a message to a Telegram channel."""
    full_text = f"{text}\n\n🔗 {article_url}"
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": full_text,
            "disable_web_page_preview": False,
        },
        timeout=10,
    )
    resp.raise_for_status()
    print("  ✅ Telegram: posted")


def run():
    print(f"\n🤖 Bot starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    posted = load_posted()

    candidates = []
    for topic in TOPICS:
        try:
            articles = fetch_articles(topic, posted)
            candidates.extend(articles)
            print(f"  📰 '{topic}': {len(articles)} new articles found")
        except Exception as e:
            print(f"  ⚠️ NewsAPI error for '{topic}': {e}")

    if not candidates:
        print("  Nothing new to post. Done.")
        return

    try:
        did, token = bluesky_login()
        bluesky_ok = True
    except Exception as e:
        print(f"  ⚠️ Bluesky login failed: {e}")
        bluesky_ok = False

    count = 0
    for article in candidates:
        if count >= ARTICLES_PER_RUN:
            break

        url = article.get("url", "")
        title = article.get("title", "")
        print(f"\n  📄 Processing: {title[:60]}...")

        try:
            summary = summarize_with_claude(article)
            post_text = build_post(summary)
            print(f"  ✍️ Post: {post_text[:120]}...")
        except Exception as e:
            print(f"  ⚠️ Claude error: {e}")
            continue

        if bluesky_ok:
            try:
                post_to_bluesky(post_text, did, token)
            except Exception as e:
                print(f"  ⚠️ Bluesky post failed: {e}")

        try:
            post_to_telegram(post_text, url)
        except Exception as e:
            print(f"  ⚠️ Telegram post failed: {e}")

        posted.add(url)
        count += 1
        time.sleep(3)

    save_posted(posted)
    print(f"\n✅ Done — posted {count} article(s)")


if __name__ == "__main__":
    run()
