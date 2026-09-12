"""
Daily News Telegram Bot (Multi-User, RSS-based)
--------------------------------------------------
Fetches fresh headlines directly from trusted news outlets' official RSS
feeds (Hindustan Times, NDTV, BBC, Reuters, TechCrunch, ESPN, etc.) and
sends a formatted digest to EVERY subscriber saved in the Google Sheet.

No third-party news API, no API key, no daily quota limits — just the
publishers' own public RSS feeds.

Required environment variables (set as GitHub Actions secrets):
    TELEGRAM_BOT_TOKEN      -> token from @BotFather
    GOOGLE_CREDENTIALS_JSON -> full content of your service account JSON,
                               pasted as a single-line string
    SHEET_NAME              -> name of your Google Sheet
                               (e.g. "news bot subscribers spreadsheet")

Run manually for testing:
    python daily_news_bot.py
"""

import os
import sys
import json
import time
import requests
import feedparser
import gspread
from google.oauth2.service_account import Credentials

# ---------- Configuration ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SHEET_NAME = os.environ.get("SHEET_NAME", "news bot subscribers spreadsheet")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Official RSS feeds per category/domain, from trusted, well-known outlets.
CATEGORY_FEEDS = {
    "india": [
        "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
        "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",
        "https://feeds.feedburner.com/ndtvnews-india-news",
    ],
    "world": [
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://feeds.feedburner.com/ndtvnews-world-news",
    ],
    "technology": [
        "http://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://techcrunch.com/feed/",
    ],
    "business": [
        "http://feeds.bbci.co.uk/news/business/rss.xml",
        "https://www.hindustantimes.com/feeds/rss/business/rssfeed.xml",
    ],
    "sports": [
        "http://feeds.bbci.co.uk/sport/rss.xml",
        "https://www.hindustantimes.com/feeds/rss/cricket/rssfeed.xml",
    ],
    "science": [
        "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    ],
    "health": [
        "http://feeds.bbci.co.uk/news/health/rss.xml",
    ],
    "entertainment": [
        "http://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
        "https://www.hindustantimes.com/feeds/rss/entertainment/rssfeed.xml",
    ],
}

# How many articles per category to include in the final digest.
ARTICLES_PER_CATEGORY = 4

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

CATEGORY_EMOJI = {
    "india": "🇮🇳",
    "world": "🌍",
    "technology": "💻",
    "business": "💼",
    "sports": "🏆",
    "science": "🔬",
    "health": "🩺",
    "entertainment": "🎬",
}


def get_all_subscribers():
    """Read every Chat ID from the Google Sheet (column A, skipping header)."""
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1

    all_rows = sheet.get_all_values()
    chat_ids = [row[0] for row in all_rows[1:] if row and row[0].strip()]
    return chat_ids


def fetch_category_news(category: str):
    """Fetch the latest entries from every RSS feed configured for a category."""
    feeds = CATEGORY_FEEDS.get(category, [])
    articles = []

    for feed_url in feeds:
        try:
            parsed = feedparser.parse(feed_url)
            entries = parsed.entries[:ARTICLES_PER_CATEGORY + 3]
            print(f"[{category}] {feed_url} -> {len(entries)} entries")
            for entry in entries:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                if title and link:
                    articles.append({"title": title, "url": link})
        except Exception as e:
            print(f"[{category}] Error fetching {feed_url}: {e}")

    return articles


def build_digest_message():
    """Build the full formatted digest message across all categories."""
    from datetime import datetime

    today = datetime.now().strftime("%d %B %Y")
    lines = [f"📅 *Daily News Digest — {today}*\n"]

    any_news_found = False
    seen_urls = set()  # tracks articles already used, so no article repeats across categories

    for category in CATEGORY_FEEDS:
        articles = fetch_category_news(category)
        if not articles:
            continue

        unique_articles = []
        for article in articles:
            url = article["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_articles.append(article)
            if len(unique_articles) >= ARTICLES_PER_CATEGORY:
                break

        if not unique_articles:
            continue

        any_news_found = True
        emoji = CATEGORY_EMOJI.get(category, "📰")
        lines.append(f"\n{emoji} *{category.upper()}*")

        for article in unique_articles:
            title = article["title"].split(" - ")[0].strip()
            url = article["url"]
            if title:
                lines.append(f"• [{title}]({url})")

    if not any_news_found:
        lines.append("\nNo news available right now. Please try again later.")

    return "\n".join(lines)


def send_telegram_message(chat_id: str, text: str):
    """Send a message to one specific Telegram chat."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    response = requests.post(TELEGRAM_API_URL, data=payload, timeout=15)
    if response.status_code != 200:
        print(f"Failed to send to {chat_id}: {response.status_code} - {response.text}")
    else:
        print(f"Message sent successfully to {chat_id}!")


def send_to_all_subscribers(message: str):
    """Send the digest to every subscriber, splitting long messages if needed."""
    subscribers = get_all_subscribers()

    if not subscribers:
        print("No subscribers found in the sheet yet.")
        return

    print(f"Sending news to {len(subscribers)} subscriber(s)...")

    chunks = split_message_by_lines(message)

    for chat_id in subscribers:
        for chunk in chunks:
            send_telegram_message(chat_id, chunk)
        time.sleep(0.3)  # small delay to avoid hitting Telegram's rate limits


def split_message_by_lines(message: str, max_len: int = 3500):
    """Split a long message into chunks WITHOUT breaking in the middle of a
    line (so markdown links like [text](url) never get cut in half)."""
    lines = message.split("\n")
    chunks = []
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > max_len and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line

    if current:
        chunks.append(current)

    return chunks


def main():
    missing = [
        name
        for name, val in [
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("GOOGLE_CREDENTIALS_JSON", GOOGLE_CREDENTIALS_JSON),
        ]
        if not val
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    message = build_digest_message()
    send_to_all_subscribers(message)


if __name__ == "__main__":
    main()
