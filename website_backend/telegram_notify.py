"""
Sends messages to the same Telegram bot/rider group the bot uses, via plain HTTP calls
to the Bot API. This lets the website notify riders without needing python-telegram-bot
or sharing a process with the bot — the bot's own handlers pick up the resulting button
presses (webclaim:/webdelivered: callback patterns) since it's the same bot token.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
RIDER_GROUP_CHAT_ID = os.environ.get("RIDER_GROUP_CHAT_ID", "-5358898377")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


def _post(method, payload):
    if not API_BASE:
        logger.warning("BOT_TOKEN not configured — skipping Telegram notification")
        return None
    try:
        resp = requests.post(f"{API_BASE}/{method}", json=payload, timeout=10)
        if not resp.ok:
            logger.error(f"Telegram API error on {method}: {resp.text}")
        return resp.json()
    except Exception:
        logger.exception(f"Failed to call Telegram API method {method}")
        return None


def broadcast_web_order_to_riders(reference, service, zone, location, errand_items, delivery_type, total):
    text = "🚴 *New Order Available!* (via website)\n\n" f"🛠️ Service: {service}\n"
    if errand_items:
        text += f"📝 Items: {errand_items}\n"
    text += (
        f"🗺️ Zone: {zone}\n"
        f"📍 Location: {location}\n"
        f"🚴 Delivery Type: {delivery_type}\n"
        f"💳 Total: ₦{total:,}\n"
        f"👤 Rider earns: ₦{int(total * 0.7):,} (70%)\n\n"
        "Paid online — no payment collection needed. First to accept gets this delivery 👇"
    )
    payload = {
        "chat_id": RIDER_GROUP_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [[{"text": "✅ Accept", "callback_data": f"webclaim:{reference}"}]]
        },
    }
    result = _post("sendMessage", payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]
    return None


def notify_admin(text):
    if not ADMIN_CHAT_ID:
        return
    _post("sendMessage", {"chat_id": ADMIN_CHAT_ID, "text": text, "parse_mode": "Markdown"})
