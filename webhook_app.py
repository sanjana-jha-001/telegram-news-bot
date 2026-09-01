"""
Telegram Webhook Listener
--------------------------
This small web app listens for incoming Telegram messages (via webhook).
When a user sends /start to the bot, it saves their Chat ID (and username,
if available) into a Google Sheet, so they become a "subscriber" for the
daily news digest.

Required environment variables:
    TELEGRAM_BOT_TOKEN     -> token from @BotFather
    GOOGLE_CREDENTIALS_JSON -> the FULL content of your service account JSON
                               file, pasted as a single-line string
    SHEET_NAME              -> the name of your Google Sheet
                                (e.g. "news bot subscribers spreadsheet")
"""

import os
import json
from flask import Flask, request
import time
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# ---------- Configuration ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SHEET_NAME = os.environ.get("SHEET_NAME", "news bot subscribers spreadsheet")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheet():
    """Connect to Google Sheets using the service account credentials."""
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).sheet1
    return sheet


def is_already_subscribed(sheet, chat_id: str) -> bool:
    """Check if this chat_id already exists in column A."""
    existing_ids = sheet.col_values(1)  # Column A = Chat_ID
    return str(chat_id) in existing_ids


def add_subscriber(chat_id: str, username: str):
    """Append a new subscriber row to the Google Sheet."""
    sheet = get_sheet()
    if is_already_subscribed(sheet, chat_id):
        return False  # already subscribed, nothing to do
    sheet.append_row([str(chat_id), username or ""])
    return True


@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """This is the URL Telegram will call whenever someone messages the bot."""
    update = request.get_json(force=True)

    message = update.get("message", {})
    text = message.get("text", "")
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    username = chat.get("username") or chat.get("first_name", "")

    if text.strip() == "/start" and chat_id:
        added = add_subscriber(chat_id, username)
        if added:
            reply = "🎉 Aap subscribe ho gaye! Ab aapko roz subah news milegi."
        else:
            reply = "Aap already subscribed hain. Roz subah news milती rahegi!"
        send_telegram_reply(chat_id, reply)

    return {"ok": True}


def send_telegram_reply(chat_id, text):
    """Send a confirmation message back to the user."""
    import requests

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})


@app.route("/", methods=["GET"])
def health_check():
    """Simple health check so you can confirm the server is alive in a browser."""
    return "Bot webhook server is running!"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
