"""
Email-based OTP verification for website customer identity, sent via Resend's
HTTPS API. Originally built on Gmail SMTP, but Render's free tier blocks
outbound SMTP ports (587/465/25) entirely to prevent spam abuse — this hit an
"OSError: Network is unreachable" in production. Resend sends over regular
HTTPS (port 443), which isn't blocked, and needs no business KYC to get started.

Codes are generated and checked here (not by Resend), stored in-memory keyed
by email. Fine for Render's free single-instance tier — if you ever scale to
multiple instances, this needs to move to the Customers sheet instead.
"""
import os
import random
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
# Resend's shared test sender — works immediately with zero setup. Once BikeBlitz
# has its own verified domain on Resend, swap this for something like
# "BikeBlitz <noreply@bikeblitz.com>" — no other code changes needed.
FROM_ADDRESS = os.environ.get("RESEND_FROM_ADDRESS", "BikeBlitz <onboarding@resend.dev>")

CODE_TTL_MINUTES = 10
CODE_MAX_ATTEMPTS = 5

_pending_codes = {}  # email -> {"code": str, "expires": datetime, "attempts": int}


def _generate_code():
    return f"{random.randint(0, 9999):04d}"


def send_code(email):
    """Generates a 4-digit code, emails it via Resend, and stashes it for later
    verification. Returns (ok: bool, error: str|None)."""
    if not RESEND_API_KEY:
        return False, "Email verification isn't configured yet — contact the admin."

    code = _generate_code()
    _pending_codes[email] = {
        "code": code,
        "expires": datetime.now() + timedelta(minutes=CODE_TTL_MINUTES),
        "attempts": 0,
    }

    payload = {
        "from": FROM_ADDRESS,
        "to": [email],
        "subject": f"Your BikeBlitz verification code: {code}",
        "text": (
            f"Your BikeBlitz verification code is {code}.\n\n"
            f"This code expires in {CODE_TTL_MINUTES} minutes. Do not share it with anyone.\n\n"
            "— BikeBlitz"
        ),
    }
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if not resp.ok:
            logger.error(f"Resend send failed: {resp.status_code} {resp.text}")
            _pending_codes.pop(email, None)
            return False, "Couldn't send the verification email — try again shortly."
        return True, None
    except Exception:
        logger.exception("Failed to call Resend API")
        _pending_codes.pop(email, None)
        return False, "Couldn't reach the email service — try again shortly."


def verify_code(email, entered_code):
    """Checks an entered code against what was sent. Returns (verified: bool, error: str|None)."""
    pending = _pending_codes.get(email)
    if not pending:
        return False, "No verification code was sent to this email — request one first."

    if datetime.now() > pending["expires"]:
        _pending_codes.pop(email, None)
        return False, "That code has expired — request a new one."

    pending["attempts"] += 1
    if pending["attempts"] > CODE_MAX_ATTEMPTS:
        _pending_codes.pop(email, None)
        return False, "Too many incorrect attempts — request a new code."

    if entered_code.strip() != pending["code"]:
        return False, "That code is incorrect."

    _pending_codes.pop(email, None)
    return True, None
