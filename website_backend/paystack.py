"""
Paystack integration. Test keys work exactly like live keys, just against Paystack's
test environment — no real money moves until you switch to live keys later.
"""
import os
import hmac
import hashlib
import logging
import requests

logger = logging.getLogger(__name__)

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")
PAYSTACK_BASE_URL = "https://api.paystack.co"


def initialize_transaction(email, amount_naira, reference, callback_url, metadata=None):
    """Creates a Paystack transaction. Amount must be sent in kobo (naira * 100).
    Returns (authorization_url, error) — error is None on success."""
    if not PAYSTACK_SECRET_KEY:
        return None, "Paystack isn't configured yet (missing PAYSTACK_SECRET_KEY)."

    payload = {
        "email": email,
        "amount": int(amount_naira) * 100,
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata or {},
    }
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}

    try:
        resp = requests.post(f"{PAYSTACK_BASE_URL}/transaction/initialize", json=payload, headers=headers, timeout=15)
        data = resp.json()
        if not data.get("status"):
            return None, data.get("message", "Paystack initialization failed.")
        return data["data"]["authorization_url"], None
    except Exception:
        logger.exception("Failed to initialize Paystack transaction")
        return None, "Couldn't reach Paystack right now — try again shortly."


def verify_transaction(reference):
    """Confirms a transaction's real status directly with Paystack (don't trust webhook
    body alone). Returns (verified_bool, amount_kobo, error)."""
    if not PAYSTACK_SECRET_KEY:
        return False, 0, "Paystack isn't configured yet."

    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    try:
        resp = requests.get(f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}", headers=headers, timeout=15)
        data = resp.json()
        if not data.get("status"):
            return False, 0, data.get("message", "Verification failed.")
        tx = data["data"]
        verified = tx.get("status") == "success"
        return verified, tx.get("amount", 0), None
    except Exception:
        logger.exception("Failed to verify Paystack transaction")
        return False, 0, "Couldn't reach Paystack right now."


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Confirms a webhook actually came from Paystack, per their HMAC SHA512 scheme."""
    if not PAYSTACK_SECRET_KEY or not signature_header:
        return False
    computed = hmac.new(PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header)
