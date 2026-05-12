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

ARTICLES_PER_RUN   = 1
POSTED_LOG         = "posted.json"
ROTATION_LOG       = "rotation.json"

CTA                = "\n\n👉 Follow for daily casino tips"
MAX_POST_LENGTH    = 300

# ── Content Rotation (cycles every 4 posts = every 16 hours) ─────────────────
# Each slot runs every 4 hours. The rotation cycles through these 4 categories.

CONTENT_SLOTS = [
    {
        "id": "news",
        "label": "Casino News",
        "topics": [
            "casino news",
            "new casino games 2025",
            "casino controversy",
            "casino cheating caught",
            "new casino opening",
            "gambling industry news",
        ],
        "prompt_style": """You are a social media writer for a casino tips page.

Your audience is casino players who want to stay informed.

Write a short news-style post with:
- 1 to 2 clear sentences about the news
- casual but informative tone
- no jargon, easy to read
- maximum 200 characters
- 2 to 3 relevant hashtags at the end, such as #CasinoNews #Gambling #Slots

Rules:
- Do NOT include any links
- Do NOT include any call to action
- Do NOT use quotation marks
- Output only the post text

Title: {title}
Description: {description}
""",
    },
    {
        "id": "tips",
        "label": "Casino Game Tips",
        "topics": [
            "casino tips beginners",
            "how to stop losing money gambling",
            "casino game strategy beginner",
            "responsible gambling tips",
            "casino bankroll management",
            "gambling mistakes to avoid",
        ],
        "prompt_style": """You are a social media writer for a casino tips page.

Your audience is beginner casino players who want to lose less money.

Write a short tip post with:
- 1 practical tip or warning about casino games
- beginner-friendly language
- direct and useful tone
- maximum 200 characters
- 2 to 3 relevant hashtags at the end, such as #CasinoTips #GamblingTips #SmartGambling

Rules:
- Do NOT include any links
- Do NOT include any call to action
- Do NOT use quotation marks
- Do NOT promote gambling, focus on playing smarter
- Output only the post text

Title: {title}
Description: {description}
""",
    },
    {
        "id": "blackjack",
        "label": "Blackjack",
        "topics": [
            "blackjack strategy",
            "blackjack tips",
            "blackjack card counting",
            "blackjack mistakes",
            "how to play blackjack",
            "blackjack odds",
        ],
        "prompt_style": """You are a social media writer for a casino tips page.

Your audience loves blackjack and wants to improve their game.

Write a short blackjack-focused post with:
- 1 specific blackjack tip, fact, or strategy insight
- clear and direct language
- feels like advice from a friend who plays well
- maximum 200 characters
- 2 to 3 relevant hashtags at the end, such as #Blackjack #BlackjackStrategy #CasinoTips

Rules:
- Do NOT include any links
- Do NOT include any call to action
- Do NOT use quotation marks
- Output only the post text

Title: {title}
Description: {description}
""",
    },
    {
        "id": "strategy",
        "label": "Casino Strategy",
        "topics": [
            "poker strategy tips",
            "roulette strategy",
            "slot machine tips",
            "casino bonus strategy",
            "blackjack basic strategy",
            "casino game odds explained",
        ],
        "prompt_style": """You are a social media writer for a casino tips page.

Your audience wants to play smarter at poker, blackjack, roulette, slots, and use bonuses better.

Write a short strategy post with:
- 1 actionable strategy tip for any casino game (poker, blackjack, roulette, slots, or bonus usage)
- clear, no-nonsense language
- feels like insider knowledge shared simply
- maximum 200 characters
- 2 to 3 relevant hashtags at the end, such as #CasinoStrategy #Poker #Roulette #Slots

Rules:
- Do NOT include any links
- Do NOT include any call to action
- Do NOT use quotation marks
- Do NOT guarantee wins, focus on smarter play
- Output only the post text

Title: {title}
Description: {description}
""",
    },
]

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


def get_current_slot() -> dict:
    """Determine which content slot to use based on rotation.
    Cycles through the 4 slots sequentially. Each run advances by 1."""
    if os.path.exists(ROTATION_LOG):
        with open(ROTATION_LOG, "r", encoding="utf-8") as f:
            data = json.load(f)
            index = data.get("next_index", 0)
    else:
        index = 0

    slot = CONTENT_SLOTS[index % len(CONTENT_SLOTS)]

    # Save next index for next run
    next_index = (index + 1) % len(CONTENT_SLOTS)
    with open(ROTATION_LOG, "w", encoding="utf-8") as f:
        json.dump({"next_index": next_index, "last_run": datetime.now().isoformat()}, f)

    return slot


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


def summarize_with_claude(article: dict, prompt_template: str) -> str:
    """Turn an article into a short social post using the slot's prompt style."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = prompt_template.format(
        title=article.get("title", ""),
        description=article.get("description", ""),
    )

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


def bluesky_login() -> tuple:
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
    print(f"\n🎰 Casino Bot starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Determine which content slot to post
    slot = get_current_slot()
    print(f"  🎯 Content slot: {slot['label']} (id: {slot['id']})")

    posted = load_posted()

    # Fetch articles for this slot's topics
    candidates = []
    for topic in slot["topics"]:
        try:
            articles = fetch_articles(topic, posted)
            candidates.extend(articles)
            print(f"  📰 '{topic}': {len(articles)} new articles found")
        except Exception as e:
            print(f"  ⚠️ NewsAPI error for '{topic}': {e}")

    if not candidates:
        print("  Nothing new to post. Done.")
        return

    # Login to Bluesky
    try:
        did, token = bluesky_login()
        bluesky_ok = True
    except Exception as e:
        print(f"  ⚠️ Bluesky login failed: {e}")
        bluesky_ok = False

    # Process and post
    count = 0
    for article in candidates:
        if count >= ARTICLES_PER_RUN:
            break

        url = article.get("url", "")
        title = article.get("title", "")
        print(f"\n  📄 Processing: {title[:60]}...")

        try:
            summary = summarize_with_claude(article, slot["prompt_style"])
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
    print(f"\n✅ Done — posted {count} article(s) [{slot['label']}]")


if __name__ == "__main__":
    run()
