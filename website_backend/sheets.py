"""
Google Sheets helpers for the BikeBlitz website backend.

This intentionally duplicates a small slice of what bikeblitz_bot.py already does,
since the bot and this backend run as separate processes/services. If pricing or
sheet structure changes in the bot, mirror the change here too.
"""
import os
import json
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

_gsheet_client = None
_spreadsheet = None


def get_spreadsheet():
    global _gsheet_client, _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        _gsheet_client = gspread.authorize(creds)
        _spreadsheet = _gsheet_client.open_by_key(GOOGLE_SHEET_ID)
        return _spreadsheet
    except Exception:
        logger.exception("Failed to connect to Google Sheets")
        return None


def get_transactions_sheet():
    ss = get_spreadsheet()
    return ss.sheet1 if ss else None


def get_online_rider_count():
    """Counts riders currently marked Online in the Riders sheet (same sheet the bot writes to)."""
    ss = get_spreadsheet()
    if ss is None:
        return 0
    try:
        ws = ss.worksheet("Riders")
        records = ws.get_all_records()
        return sum(1 for r in records if r.get("Availability") == "Online")
    except Exception:
        logger.exception("Failed to count online riders")
        return 0


def get_weborders_sheet():
    ss = get_spreadsheet()
    if ss is None:
        return None
    try:
        import gspread
        try:
            return ss.worksheet("WebOrders")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="WebOrders", rows=1000, cols=15)
            ws.append_row([
                "Reference", "Customer Name", "Phone", "Service", "Zone", "Location",
                "Errand Items", "Delivery Type", "Total", "Status", "Rider ID",
                "Rider Name", "Broadcast Message ID", "Timestamp", "Pickup Code"
            ])
            return ws
    except Exception:
        logger.exception("Failed to access WebOrders worksheet")
        return None


def create_web_order(reference, customer_name, phone, service, zone, location, errand_items, delivery_type, total):
    """Creates a new WebOrders row in Pending status (before payment is confirmed)."""
    ws = get_weborders_sheet()
    if ws is None:
        return False
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ws.append_row([
        reference, customer_name, phone, service, zone, location,
        errand_items, delivery_type, total, "Pending Payment", "", "", "", timestamp
    ])
    return True


def get_web_order(reference):
    ws = get_weborders_sheet()
    if ws is None:
        return None
    try:
        rows = ws.get_all_values()
        headers = rows[0] if rows else []
        for row in rows[1:]:
            if row and row[0] == reference:
                return dict(zip(headers, row))
        return None
    except Exception:
        logger.exception("Failed to fetch web order")
        return None


def update_web_order(reference, **fields):
    ws = get_weborders_sheet()
    if ws is None:
        return False
    try:
        rows = ws.get_all_values()
        headers = rows[0] if rows else []
        for idx, row in enumerate(rows[1:], start=2):
            if row and row[0] == reference:
                for key, value in fields.items():
                    if key in headers:
                        col_idx = headers.index(key) + 1
                        col_letter = chr(ord("A") + col_idx - 1)
                        ws.update(f"{col_letter}{idx}", [[value]])
                return True
        return False
    except Exception:
        logger.exception("Failed to update web order")
        return False


def log_transaction(customer_name, telegram_id, service, zone, location, delivery_type, total):
    """Appends a row to the main Transactions sheet, same shape the bot uses,
    so /stats, /export, and reporting stay unified across bot + website orders."""
    sheet = get_transactions_sheet()
    if sheet is None:
        return None
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([
        timestamp, customer_name, str(telegram_id or "WEB"), service, zone,
        location, delivery_type, total, "Pending", ""
    ])
    return len(sheet.get_all_values())


# ---------- Website customer identity (phone + OTP based) ----------
# This is the website's own customer identity table, keyed by phone number,
# separate from the bot's Telegram-ID-based identity in the Riders/Transactions
# sheets. A customer who orders via both bot and website currently has two
# separate histories — unifying them is a future step, not this one.

def get_customers_sheet():
    """Returns the 'Customers' worksheet, creating it with headers if it doesn't exist yet."""
    ss = get_spreadsheet()
    if ss is None:
        return None
    try:
        import gspread
        try:
            return ss.worksheet("Customers")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="Customers", rows=1000, cols=7)
            ws.append_row([
                "Email", "Phone", "Name", "Session Token", "Wallet Balance",
                "Referral Code", "Credit Balance"
            ])
            return ws
    except Exception:
        logger.exception("Failed to access Customers worksheet")
        return None


def get_or_create_customer(email, phone="", name=""):
    """Ensures a Customers row exists for this email; returns the row dict with a
    freshly generated session token. Phone is stored too (even though email is the
    identity key) so order history can still be matched against WebOrders, which is
    keyed by phone. Call this only right after code verification succeeds, not on
    every request — each call issues (and overwrites) a new token."""
    ws = get_customers_sheet()
    if ws is None:
        return None
    try:
        rows = ws.get_all_values()
        headers = rows[0] if rows else []
        token = uuid.uuid4().hex
        for idx, row in enumerate(rows[1:], start=2):
            if row and row[0] == email:
                ws.update(f"D{idx}", [[token]])
                if phone:
                    ws.update(f"B{idx}", [[phone]])
                record = dict(zip(headers, row))
                record["Session Token"] = token
                if phone:
                    record["Phone"] = phone
                return record
        ws.append_row([email, phone, name, token, 0, "", 0])
        return {
            "Email": email, "Phone": phone, "Name": name, "Session Token": token,
            "Wallet Balance": "0", "Referral Code": "", "Credit Balance": "0",
        }
    except Exception:
        logger.exception("Failed to get/create customer")
        return None


def get_customer_by_token(token):
    """Looks up a customer by their session token — used to authenticate requests
    from the website (sent as a header or query param) without needing OTP every time."""
    ws = get_customers_sheet()
    if ws is None:
        return None
    try:
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Session Token", "")) == str(token):
                return r
        return None
    except Exception:
        logger.exception("Failed to look up customer by token")
        return None


def is_blocked(identifier):
    """Checks the shared 'Blocklist' sheet (same one bikeblitz_bot.py writes to)
    for a match. The bot blocks by Telegram ID, but that column is really just a
    generic identifier string — an admin can also add a phone number there to
    block a web-only customer who has no Telegram ID. Matches against either the
    'Telegram ID' column value directly."""
    ss = get_spreadsheet()
    if ss is None:
        return False
    try:
        ws = ss.worksheet("Blocklist")
        records = ws.get_all_records()
        return any(str(r.get("Telegram ID", "")) == str(identifier) for r in records)
    except Exception:
        logger.exception("Failed to check blocklist")
        return False


def record_rider_reassignment(rider_id):
    """Increments a rider's reassignment/no-show count in the shared 'Riders'
    sheet (column J), same one bikeblitz_bot.py writes to for bot-native orders.
    Doesn't create the column/sheet if missing — the bot already manages that
    structure, this just adds to it. Returns the new count, or 0 on failure."""
    ss = get_spreadsheet()
    if ss is None:
        return 0
    try:
        ws = ss.worksheet("Riders")
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 1 and row[1] == str(rider_id):
                current = int(row[9]) if len(row) > 9 and str(row[9]).isdigit() else 0
                new_count = current + 1
                ws.update(f"J{idx}", [[new_count]])
                return new_count
        return 0
    except Exception:
        logger.exception("Failed to record rider reassignment")
        return 0
