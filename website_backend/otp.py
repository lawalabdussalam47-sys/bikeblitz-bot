"""
Termii OTP helpers for website customer phone verification.
Uses Termii's generic channel with the default shared sender name, so no
approved Sender ID is required yet. Once BikeBlitz has its own approved
Sender ID, just set TERMII_SENDER_ID in the environment and it's picked up
automatically — no other code changes needed.
"""
import os
import logging
import requests

logger = logging.getLogger(__name__)

TERMII_API_KEY = os.environ.get("TERMII_API_KEY")
TERMII_SENDER_ID = os.environ.get("TERMII_SENDER_ID", "Termii")  # shared default until BikeBlitz has its own
TERMII_BASE_URL = "https://api.ng.termii.com/api"

OTP_LENGTH = 4
OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 3


def send_otp(phone):
    """Sends a 4-digit OTP to a Nigerian phone number via Termii.
    Expects phone in international format without '+' (e.g. 2348012345678).
    Returns (pin_id, error) — pin_id is None on failure."""
    if not TERMII_API_KEY:
        return None, "OTP service isn't configured yet — contact the admin."

    payload = {
        "api_key": TERMII_API_KEY,
        "message_type": "NUMERIC",
        "to": phone,
        "from": TERMII_SENDER_ID,
        "channel": "generic",
        "pin_attempts": OTP_MAX_ATTEMPTS,
        "pin_time_to_live": OTP_TTL_MINUTES,
        "pin_length": OTP_LENGTH,
        "pin_placeholder": "< 1234 >",
        "message_text": "Your BikeBlitz verification code is < 1234 >. It expires in 10 minutes. Do not share this code.",
        "pin_type": "NUMERIC",
    }
    try:
        resp = requests.post(f"{TERMII_BASE_URL}/sms/otp/send", json=payload, timeout=15)
        data = resp.json()
        if not resp.ok or not data.get("pinId"):
            logger.error(f"Termii send OTP failed: {data}")
            return None, "Couldn't send the verification code — try again shortly."
        return data["pinId"], None
    except Exception:
        logger.exception("Failed to call Termii OTP send")
        return None, "Couldn't reach the verification service — try again shortly."


def verify_otp(pin_id, pin):
    """Verifies a customer-entered OTP against Termii. Returns (verified: bool, error)."""
    if not TERMII_API_KEY:
        return False, "OTP service isn't configured yet — contact the admin."

    payload = {"api_key": TERMII_API_KEY, "pin_id": pin_id, "pin": pin}
    try:
        resp = requests.post(f"{TERMII_BASE_URL}/sms/otp/verify", json=payload, timeout=15)
        data = resp.json()
        verified = data.get("verified") in (True, "True", "true")
        if not resp.ok:
            logger.error(f"Termii verify OTP failed: {data}")
            return False, "Couldn't verify that code — try again."
        return verified, None if verified else "That code is incorrect or has expired."
    except Exception:
        logger.exception("Failed to call Termii OTP verify")
        return False, "Couldn't reach the verification service — try again shortly."
