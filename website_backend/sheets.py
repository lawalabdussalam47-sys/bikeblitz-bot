"""
Google Sheets helpers for the BikeBlitz website backend.

This intentionally duplicates a small slice of what bikeblitz_bot.py already does,
since the bot and this backend run as separate processes/services. If pricing or
sheet structure changes in the bot, mirror the change here too.
"""
import os
import json
import logging
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
            ws = ss.add_worksheet(title="WebOrders", rows=1000, cols=14)
            ws.append_row([
                "Reference", "Customer Name", "Phone", "Service", "Zone", "Location",
                "Errand Items", "Delivery Type", "Total", "Status", "Rider ID",
                "Rider Name", "Broadcast Message ID", "Timestamp"
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
