"""
Email-based OTP verification for website customer identity, sent via Gmail SMTP.
Switched to email instead of SMS after discovering Termii requires business KYC
(CAC registration) before it'll activate Nigeria for OTP SMS sending — this sidesteps
that entirely, at zero cost, since customers already provide an email at checkout.

Codes are generated and checked here (not by a third-party OTP service), stored
in-memory keyed by email. Fine for Render's free single-instance tier — if you ever
scale to multiple instances, this needs to move to the Customers sheet instead.
"""
import os
import random
import smtplib
import logging
from email.mime.text import MIMEText
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

CODE_TTL_MINUTES = 10
CODE_MAX_ATTEMPTS = 5

_pending_codes = {}  # email -> {"code": str, "expires": datetime, "attempts": int}


def _generate_code():
    return f"{random.randint(0, 9999):04d}"


def send_code(email):
    """Generates a 4-digit code, emails it, and stashes it for later verification.
    Returns (ok: bool, error: str|None)."""
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        return False, "Email verification isn't configured yet — contact the admin."

    code = _generate_code()
    _pending_codes[email] = {
        "code": code,
        "expires": datetime.now() + timedelta(minutes=CODE_TTL_MINUTES),
        "attempts": 0,
    }

    body = (
        f"Your BikeBlitz verification code is {code}.\n\n"
        f"This code expires in {CODE_TTL_MINUTES} minutes. Do not share it with anyone.\n\n"
        "— BikeBlitz"
    )
    msg = MIMEText(body)
    msg["Subject"] = f"Your BikeBlitz verification code: {code}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, [email], msg.as_string())
        return True, None
    except Exception:
        logger.exception("Failed to send verification email")
        _pending_codes.pop(email, None)
        return False, "Couldn't send the verification email — try again shortly."


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
