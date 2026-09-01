"""
Daily News Telegram Bot (Multi-User)
--------------------------------------
Fetches top headlines across multiple categories (general, technology,
business, sports) using NewsAPI.org and sends a formatted digest message
to EVERY subscriber saved in the Google Sheet.

Required environment variables (set as GitHub Actions secrets):
    TELEGRAM_BOT_TOKEN      -> token from @BotFather
    NEWS_API_KEY            -> API key from https://newsapi.org
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
import gspread
from google.oauth2.service_account import Credentials

# ---------- Configuration ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SHEET_NAME = os.environ.get("SHEET_NAME", "news bot subscribers spreadsheet")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Search keywords per category/domain. We use the /v2/everything endpoint
# instead of /v2/top-headlines because NewsAPI's free "Developer" plan often
# returns 0 results for top-headlines with a country filter. /v2/everything
# works reliably on the free tier and lets us pull global news per domain.
CATEGORY_QUERIES = {
    "world": "world news OR breaking news",
    "technology": "technology OR AI OR startup",
    "business": "business OR economy OR markets",
    "sports": "sports OR football OR cricket",
    "science": "science OR space OR research",
    "health": "health OR medicine OR wellness",
    "entertainment": "entertainment OR movies OR celebrity",
}

# How many articles per category to include.
ARTICLES_PER_CATEGORY = 3

NEWS_API_URL = "https://newsapi.org/v2/everything"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

CATEGORY_EMOJI = {
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
    # Skip the header row (row 1), take column A (Chat_ID) from every other row.
    chat_ids = [row[0] for row in all_rows[1:] if row and row[0].strip()]
    return chat_ids


def fetch_category_news(category: str):
    """Fetch recent articles for a single category from NewsAPI's /everything endpoint."""
    query = CATEGORY_QUERIES.get(category, category)
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": ARTICLES_PER_CATEGORY,
        "apiKey": NEWS_API_KEY,
    }
    try:
        response = requests.get(NEWS_API_URL, params=params, timeout=15)
        data = response.json()
        status = data.get("status")
        total = data.get("totalResults")
        print(f"[{category}] HTTP {response.status_code} | status={status} | totalResults={total}")
        if status != "ok":
            print(f"[{category}] API message: {data.get('message')}")
        return data.get("articles", [])
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {category} news: {e}")
        return []


def build_digest_message():
    """Build the full formatted digest message across all categories."""
    from datetime import datetime

    today = datetime.now().strftime("%d %B %Y")
    lines = [f"📅 *Daily News Digest — {today}*\n"]

    any_news_found = False

    for category in CATEGORY_QUERIES:
        articles = fetch_category_news(category)
        if not articles:
            continue

        any_news_found = True
        emoji = CATEGORY_EMOJI.get(category, "📰")
        lines.append(f"\n{emoji} *{category.upper()}*")

        for article in articles:
            title = article.get("title", "").split(" - ")[0].strip()
            url = article.get("url", "")
            if title:
                lines.append(f"• [{title}]({url})")

    if not any_news_found:
        lines.append("\nNo news available right now. Please check your API key or quota.")

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

    # Telegram has a 4096 character limit per message; split if needed.
    MAX_LEN = 4000
    chunks = (
        [message]
        if len(message) <= MAX_LEN
        else [message[i : i + MAX_LEN] for i in range(0, len(message), MAX_LEN)]
    )

    for chat_id in subscribers:
        for chunk in chunks:
            send_telegram_message(chat_id, chunk)
        time.sleep(0.3)  # small delay to avoid hitting Telegram's rate limits


def main():
    missing = [
        name
        for name, val in [
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("NEWS_API_KEY", NEWS_API_KEY),
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
