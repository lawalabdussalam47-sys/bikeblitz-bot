import os
import json
import logging
from datetime import datetime, timedelta, time as dt_time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

# Bot token — MUST come from an environment variable. Never hardcode it here.
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

# Telegram chat ID that receives payment screenshots and order notifications
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "8959243289"))

# Telegram group chat ID where confirmed orders are broadcast to riders
RIDER_GROUP_CHAT_ID = int(os.environ.get("RIDER_GROUP_CHAT_ID", "-5358898377"))

# How long an order can sit unclaimed before we alert everyone
UNCLAIMED_ALERT_MINUTES = int(os.environ.get("UNCLAIMED_ALERT_MINUTES", "10"))

# --- Google Sheets transaction logging ---
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

_gsheet_client = None
_spreadsheet = None


def get_spreadsheet():
    """Lazily connect to the Google Sheet workbook. Returns None if not configured or on error."""
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


def get_sheet():
    """Returns the main transactions worksheet (first tab)."""
    ss = get_spreadsheet()
    return ss.sheet1 if ss else None


def get_riders_sheet():
    """Returns the 'Riders' worksheet, creating it with headers if it doesn't exist yet."""
    ss = get_spreadsheet()
    if ss is None:
        return None
    try:
        import gspread
        try:
            return ss.worksheet("Riders")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="Riders", rows=200, cols=4)
            ws.append_row(["Rider Name", "Telegram ID", "Deliveries Claimed", "Last Delivery"])
            return ws
    except Exception:
        logger.exception("Failed to access Riders worksheet")
        return None


def log_transaction(customer_name, telegram_id, service, zone, location, delivery_type, total):
    """Append one approved transaction as a new row. Returns the sheet row number, or None on failure."""
    try:
        sheet = get_sheet()
        if sheet is None:
            logger.warning("Google Sheets not configured — skipping transaction log")
            return None
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            timestamp, customer_name, str(telegram_id), service, zone,
            location, delivery_type, total, "Pending", ""
        ])
        return len(sheet.get_all_values())
    except Exception:
        logger.exception("Failed to log transaction to Google Sheets")
        return None


def mark_transaction_delivered(sheet_row):
    """Update a transaction row's Status (col I) and Delivered At (col J) once a rider marks it done."""
    if not sheet_row:
        return
    try:
        sheet = get_sheet()
        if sheet is None:
            return
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.update(f"I{sheet_row}:J{sheet_row}", [["Delivered", now_str]])
    except Exception:
        logger.exception("Failed to update delivery status in Google Sheets")


def get_customer_last_order(telegram_id):
    """Look up the most recent order for a given customer, for the /status command."""
    try:
        sheet = get_sheet()
        if sheet is None:
            return None
        records = sheet.get_all_records()
        matches = [r for r in records if str(r.get("Telegram ID", "")) == str(telegram_id)]
        return matches[-1] if matches else None
    except Exception:
        logger.exception("Failed to look up customer order status")
        return None


def get_todays_stats():
    """Summarize today's orders for the /stats command."""
    try:
        sheet = get_sheet()
        if sheet is None:
            return None
        records = sheet.get_all_records()
        today_str = datetime.now().strftime("%Y-%m-%d")
        todays = [r for r in records if str(r.get("Timestamp", "")).startswith(today_str)]
        total_orders = len(records)
        total_revenue = sum(int(r.get("Total", 0) or 0) for r in records)
        today_orders = len(todays)
        today_revenue = sum(int(r.get("Total", 0) or 0) for r in todays)
        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "today_orders": today_orders,
            "today_revenue": today_revenue,
        }
    except Exception:
        logger.exception("Failed to compute stats")
        return None


def get_week_stats():
    """Summarize the last 7 days of orders, and the top rider by completions, for the weekly summary."""
    try:
        sheet = get_sheet()
        if sheet is None:
            return None
        records = sheet.get_all_records()
        cutoff = datetime.now() - timedelta(days=7)
        week_records = []
        for r in records:
            try:
                ts = datetime.strptime(str(r.get("Timestamp", "")), "%Y-%m-%d %H:%M:%S")
                if ts >= cutoff:
                    week_records.append(r)
            except ValueError:
                continue

        week_orders = len(week_records)
        week_revenue = sum(int(r.get("Total", 0) or 0) for r in week_records)

        zone_counts = {}
        for r in week_records:
            z = r.get("Zone", "N/A")
            zone_counts[z] = zone_counts.get(z, 0) + 1
        busiest_zone = max(zone_counts, key=zone_counts.get) if zone_counts else "N/A"

        top_rider_name, top_rider_count = "N/A", 0
        ws = get_riders_sheet()
        if ws is not None:
            rider_records = ws.get_all_records()
            for r in rider_records:
                completed = int(r.get("Completed Deliveries", 0) or 0)
                if completed > top_rider_count:
                    top_rider_count = completed
                    top_rider_name = r.get("Rider Name", "N/A")

        return {
            "week_orders": week_orders,
            "week_revenue": week_revenue,
            "busiest_zone": busiest_zone,
            "top_rider_name": top_rider_name,
            "top_rider_count": top_rider_count,
        }
    except Exception:
        logger.exception("Failed to compute weekly stats")
        return None


async def send_cutoff_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job — reminds the rider group that the 8pm same-day cutoff is approaching."""
    try:
        await context.bot.send_message(
            chat_id=RIDER_GROUP_CHAT_ID,
            text="⏰ *Heads up!* Same-day order cutoff is in 30 minutes (8:00 PM). Wrap up active deliveries soon! 🚴",
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Failed to send cutoff reminder")


async def send_weekly_summary(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job — posts a weekly recap to the admin every Sunday night."""
    data = get_week_stats()
    if data is None:
        return
    msg = (
        "📊 *BikeBlitz Weekly Recap*\n\n"
        f"📦 Orders this week: {data['week_orders']}\n"
        f"💳 Revenue this week: ₦{data['week_revenue']:,}\n"
        f"🗺️ Busiest zone: {data['busiest_zone']}\n"
        f"🏆 Top rider: {data['top_rider_name']} ({data['top_rider_count']} deliveries)\n\n"
        "Have a great week ahead! 🚴"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg, parse_mode="Markdown")
    except Exception:
        logger.exception("Failed to send weekly summary")


def record_rider_delivery(rider_id, rider_name):
    """Increment a rider's claimed-delivery count, or add them if it's their first."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            logger.warning("Google Sheets not configured — skipping rider leaderboard update")
            return
        rows = ws.get_all_values()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 1 and row[1] == str(rider_id):
                current_count = int(row[2]) if len(row) > 2 and row[2].isdigit() else 0
                ws.update(f"A{idx}:D{idx}", [[rider_name, str(rider_id), current_count + 1, now_str]])
                return
        ws.append_row([rider_name, str(rider_id), 1, now_str])
    except Exception:
        logger.exception("Failed to update rider leaderboard")


def record_rider_completion(rider_id, order_total=0):
    """Increment a rider's completed-delivery count (col E) and cumulative earnings (col G)."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            return
        rows = ws.get_all_values()
        if rows and len(rows[0]) < 5:
            ws.update("E1", [["Completed Deliveries"]])
        if rows and len(rows[0]) < 7:
            ws.update("G1", [["Total Earnings"]])
        rider_earning = int(order_total * 0.7)
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 1 and row[1] == str(rider_id):
                current_count = int(row[4]) if len(row) > 4 and row[4].isdigit() else 0
                current_earnings = int(row[6]) if len(row) > 6 and row[6].isdigit() else 0
                ws.update(f"E{idx}", [[current_count + 1]])
                ws.update(f"G{idx}", [[current_earnings + rider_earning]])
                return
    except Exception:
        logger.exception("Failed to update rider completion count")


def get_rider_stats(rider_id):
    """Fetch one rider's completed count and total earnings, for /myearnings."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            return None
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Telegram ID")) == str(rider_id):
                return r
        return None
    except Exception:
        logger.exception("Failed to fetch rider stats")
        return None

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
(
    CHOOSING_SERVICE,
    CHOOSING_ZONE,
    CHOOSING_WEIGHT,
    CHOOSING_BUSSTOP,
    CHOOSING_ERRAND,
    CONFIRMING_ORDER,
    SCHEDULING_TIME,
    AWAITING_PAYMENT_PROOF,
    CHOOSING_LOCATION_DETAILS,
    AWAITING_SUPPORT_MESSAGE,
    AWAITING_ERRAND_ITEMS,
    AWAITING_PROMO_CODE,
) = range(12)

(
    APPLY_NAME,
    APPLY_PHONE,
    APPLY_ZONE,
    APPLY_BIKE,
    APPLY_AVAILABILITY,
    APPLY_JUDGMENT,
) = range(12, 18)

# Pricing
ZONE_PRICES = {
    "Zone 1 - On Campus": {"Light": 300, "Medium": 500, "Heavy": 700},
    "Zone 2 - Near Off Campus": {"Light": 500, "Medium": 700, "Heavy": 900},
    "Zone 3 - Mid Off Campus": {"Light": 700, "Medium": 900, "Heavy": 1100},
    "Zone 4 - Far Off Campus": {"Light": 1200, "Medium": 1400, "Heavy": 1600},
}

ERRAND_FEES = {
    "Simple Errand / Food Order": 100,
    "Complex Errand / Bulk Shopping": 250,
}

EXPRESS_SURCHARGE = 300
DISTANCE_MODIFIER = 200

# --- Referral program ---
REFERRAL_BONUS_REFERRER = 200
REFERRAL_BONUS_REFERRED = 100
REFERRAL_CREDIT_MAX_PERCENT = 50  # credit can cover at most this % of a single order's total

ZONE_LOCATIONS = {
    "Zone 1 - On Campus": "Anywhere within FUNAAB campus",
    "Zone 2 - Near Off Campus": "Harmony, Accord, Zoo, Agbede, Kofesu",
    "Zone 3 - Mid Off Campus": "Labuta, Isolu-Cele, Isolu-FUNIS, Camp",
    "Zone 4 - Far Off Campus": "Town",
}


# ---------- Referral program helpers ----------

def get_referrals_sheet():
    """Returns the 'Referrals' worksheet, creating it with headers if it doesn't exist yet."""
    ss = get_spreadsheet()
    if ss is None:
        return None
    try:
        import gspread
        try:
            return ss.worksheet("Referrals")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="Referrals", rows=500, cols=6)
            ws.append_row(["Telegram ID", "Name", "Referral Code", "Referred By Code", "Credit Balance", "Total Referred"])
            return ws
    except Exception:
        logger.exception("Failed to access Referrals worksheet")
        return None


def generate_referral_code(user_id):
    return f"BB{user_id % 100000:05d}"


def get_or_create_referral_row(user_id, user_name):
    """Ensure a customer has a row in Referrals; return (row_index, row_values_list)."""
    try:
        ws = get_referrals_sheet()
        if ws is None:
            return None, None
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 0 and row[0] == str(user_id):
                return idx, row
        code = generate_referral_code(user_id)
        ws.append_row([str(user_id), user_name, code, "", 0, 0])
        return len(rows) + 1, [str(user_id), user_name, code, "", "0", "0"]
    except Exception:
        logger.exception("Failed to get/create referral row")
        return None, None


def get_referral_code_owner(code):
    """Find the Referrals row matching a given referral code."""
    try:
        ws = get_referrals_sheet()
        if ws is None:
            return None
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Referral Code", "")).upper() == code.upper():
                return r
        return None
    except Exception:
        logger.exception("Failed to look up referral code owner")
        return None


def redeem_referral_code(user_id, user_name, code):
    """Apply a referral code redemption: credit both parties. Returns (success, message)."""
    try:
        ws = get_referrals_sheet()
        if ws is None:
            return False, "Referral system isn't set up yet."

        owner = get_referral_code_owner(code)
        if owner is None:
            return False, "❌ That referral code doesn't exist."
        if str(owner.get("Telegram ID")) == str(user_id):
            return False, "❌ You can't use your own referral code."

        row_idx, row = get_or_create_referral_row(user_id, user_name)
        if row_idx is None:
            return False, "Referral system isn't set up yet."
        if row[3]:
            return False, "❌ You've already used a referral code."

        rows = ws.get_all_values()
        for idx, r in enumerate(rows[1:], start=2):
            if len(r) > 0 and r[0] == str(user_id):
                current_credit = int(r[4]) if len(r) > 4 and str(r[4]).isdigit() else 0
                ws.update(f"D{idx}:E{idx}", [[code.upper(), current_credit + REFERRAL_BONUS_REFERRED]])
                break
        for idx, r in enumerate(rows[1:], start=2):
            if len(r) > 0 and r[0] == str(owner.get("Telegram ID")):
                current_credit = int(r[4]) if len(r) > 4 and str(r[4]).isdigit() else 0
                current_referred = int(r[5]) if len(r) > 5 and str(r[5]).isdigit() else 0
                ws.update(f"E{idx}:F{idx}", [[current_credit + REFERRAL_BONUS_REFERRER, current_referred + 1]])
                break

        return True, (
            f"✅ Referral applied! You've earned ₦{REFERRAL_BONUS_REFERRED} credit toward your next order.\n\n"
            "_Credit is applied automatically at checkout._"
        )
    except Exception:
        logger.exception("Failed to redeem referral code")
        return False, "Something went wrong redeeming that code — try again shortly."


def get_credit_balance(user_id):
    try:
        ws = get_referrals_sheet()
        if ws is None:
            return 0
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Telegram ID")) == str(user_id):
                return int(r.get("Credit Balance", 0) or 0)
        return 0
    except Exception:
        logger.exception("Failed to fetch credit balance")
        return 0


def deduct_credit(user_id, amount):
    if not amount:
        return
    try:
        ws = get_referrals_sheet()
        if ws is None:
            return
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 0 and row[0] == str(user_id):
                current = int(row[4]) if len(row) > 4 and str(row[4]).isdigit() else 0
                ws.update(f"E{idx}", [[max(0, current - amount)]])
                return
    except Exception:
        logger.exception("Failed to deduct credit")


# ---------- Promo code helpers ----------

def get_promo_sheet():
    """Returns the 'PromoCodes' worksheet, creating it with headers if it doesn't exist yet."""
    ss = get_spreadsheet()
    if ss is None:
        return None
    try:
        import gspread
        try:
            return ss.worksheet("PromoCodes")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="PromoCodes", rows=200, cols=7)
            ws.append_row(["Code", "Type", "Value", "Max Uses", "Times Used", "Active", "Expiry"])
            return ws
    except Exception:
        logger.exception("Failed to access PromoCodes worksheet")
        return None


def create_promo_code(code, promo_type, value, max_uses, expiry):
    try:
        ws = get_promo_sheet()
        if ws is None:
            return False, "Google Sheets isn't configured yet."
        rows = ws.get_all_values()
        for row in rows[1:]:
            if len(row) > 0 and row[0].upper() == code.upper():
                return False, "That code already exists."
        ws.append_row([code.upper(), promo_type, value, max_uses, 0, "Yes", expiry or ""])
        return True, f"Promo code *{code.upper()}* created."
    except Exception:
        logger.exception("Failed to create promo code")
        return False, "Something went wrong creating that code."


def get_promo_code(code):
    try:
        ws = get_promo_sheet()
        if ws is None:
            return None
        records = ws.get_all_records()
        for r in records:
            if str(r.get("Code", "")).upper() == code.upper():
                return r
        return None
    except Exception:
        logger.exception("Failed to fetch promo code")
        return None


def validate_promo_code(code):
    """Returns (valid, discount_type, discount_value, message)."""
    promo = get_promo_code(code)
    if promo is None:
        return False, None, None, "❌ That promo code doesn't exist."
    if str(promo.get("Active", "Yes")).strip().lower() != "yes":
        return False, None, None, "❌ That promo code is no longer active."
    expiry = promo.get("Expiry", "")
    if expiry:
        try:
            expiry_date = datetime.strptime(str(expiry), "%Y-%m-%d")
            if datetime.now() > expiry_date:
                return False, None, None, "❌ That promo code has expired."
        except ValueError:
            pass
    max_uses = int(promo.get("Max Uses", 0) or 0)
    times_used = int(promo.get("Times Used", 0) or 0)
    if max_uses and times_used >= max_uses:
        return False, None, None, "❌ That promo code has reached its usage limit."
    promo_type = str(promo.get("Type", "percent")).strip().lower()
    value = int(promo.get("Value", 0) or 0)
    return True, promo_type, value, "Valid"


def increment_promo_usage(code):
    try:
        ws = get_promo_sheet()
        if ws is None:
            return
        rows = ws.get_all_values()
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 0 and row[0].upper() == code.upper():
                current = int(row[4]) if len(row) > 4 and row[4].isdigit() else 0
                ws.update(f"E{idx}", [[current + 1]])
                return
    except Exception:
        logger.exception("Failed to increment promo usage")


# ---------- Rider application helpers ----------

def get_applications_sheet():
    """Returns the 'Applications' worksheet, creating it with headers if it doesn't exist yet."""
    ss = get_spreadsheet()
    if ss is None:
        return None
    try:
        import gspread
        try:
            return ss.worksheet("Applications")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="Applications", rows=300, cols=9)
            ws.append_row([
                "Timestamp", "Telegram ID", "Name", "Phone", "Zone",
                "Bike", "Availability", "Judgment Answer", "Status"
            ])
            return ws
    except Exception:
        logger.exception("Failed to access Applications worksheet")
        return None


def save_application(user_id, name, phone, zone, bike, availability, judgment_answer):
    """Append a new rider application row. Returns the sheet row number, or None on failure."""
    try:
        ws = get_applications_sheet()
        if ws is None:
            return None
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([timestamp, str(user_id), name, phone, zone, bike, availability, judgment_answer, "Pending"])
        return len(ws.get_all_values())
    except Exception:
        logger.exception("Failed to save rider application")
        return None


def update_application_status(row, status):
    if not row:
        return
    try:
        ws = get_applications_sheet()
        if ws is None:
            return
        ws.update(f"I{row}", [[status]])
    except Exception:
        logger.exception("Failed to update application status")


# ---------- Keyboards ----------

def main_menu():
    keyboard = [
        [KeyboardButton("📦 Send a Package"), KeyboardButton("🛒 Errand / Food / Market")],
        [KeyboardButton("⚡ Express Delivery"), KeyboardButton("📅 Schedule Delivery")],
        [KeyboardButton("💰 Price Quote"), KeyboardButton("🗺️ View Zones")],
        [KeyboardButton("💳 Payment Info"), KeyboardButton("📞 Contact Us")],
        [KeyboardButton("ℹ️ About BikeBlitz")],
        [KeyboardButton("🆘 Report an Issue")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def zone_keyboard():
    keyboard = [
        [KeyboardButton("Zone 1 - On Campus")],
        [KeyboardButton("Zone 2 - Near Off Campus")],
        [KeyboardButton("Zone 3 - Mid Off Campus")],
        [KeyboardButton("Zone 4 - Far Off Campus")],
        [KeyboardButton("🏠 Main Menu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def weight_keyboard():
    keyboard = [
        [KeyboardButton("Light (fits in one hand)")],
        [KeyboardButton("Medium (requires two hands)")],
        [KeyboardButton("Heavy (requires effort to carry)")],
        [KeyboardButton("Very Heavy (10kg+)")],
        [KeyboardButton("🏠 Main Menu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def busstop_keyboard():
    keyboard = [
        [KeyboardButton("✅ Close to bus stop")],
        [KeyboardButton("⚠️ Far from bus stop (+₦200)")],
        [KeyboardButton("🏠 Main Menu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def errand_keyboard():
    keyboard = [
        [KeyboardButton("Simple Errand / Food Order")],
        [KeyboardButton("Complex Errand / Bulk Shopping")],
        [KeyboardButton("🏠 Main Menu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def delivery_type_keyboard():
    keyboard = [
        [KeyboardButton("⚡ Express Delivery")],
        [KeyboardButton("📅 Schedule Delivery")],
        [KeyboardButton("🏠 Main Menu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def confirm_keyboard():
    keyboard = [
        [KeyboardButton("✅ Confirm Order")],
        [KeyboardButton("🎟️ Apply Promo Code")],
        [KeyboardButton("❌ Cancel Order")],
        [KeyboardButton("🏠 Main Menu")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def apply_zone_keyboard():
    keyboard = [
        [KeyboardButton("Zone 1 - On Campus")],
        [KeyboardButton("Zone 2 - Near Off Campus")],
        [KeyboardButton("Zone 3 - Mid Off Campus")],
        [KeyboardButton("Zone 4 - Far Off Campus")],
        [KeyboardButton("❌ Cancel")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def parse_weight(text):
    if "Light" in text:
        return "Light"
    elif "Medium" in text:
        return "Medium"
    elif "Heavy (requires effort" in text:
        return "Heavy"
    elif "Very Heavy" in text:
        return "Very Heavy"
    return None


def record_rating(customer_name, rider_name, rider_id, stars):
    """Append a delivery rating to the 'Ratings' worksheet, creating it if missing."""
    try:
        ss = get_spreadsheet()
        if ss is None:
            return
        import gspread
        try:
            ws = ss.worksheet("Ratings")
        except gspread.exceptions.WorksheetNotFound:
            ws = ss.add_worksheet(title="Ratings", rows=500, cols=5)
            ws.append_row(["Timestamp", "Customer Name", "Rider Name", "Rider ID", "Stars"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([timestamp, customer_name, rider_name, str(rider_id), stars])
    except Exception:
        logger.exception("Failed to record rating")


def get_all_customer_ids():
    """Return a sorted list of unique customer Telegram IDs from the Transactions sheet."""
    try:
        sheet = get_sheet()
        if sheet is None:
            return []
        records = sheet.get_all_records()
        ids = {str(r.get("Telegram ID")) for r in records if r.get("Telegram ID")}
        return list(ids)
    except Exception:
        logger.exception("Failed to fetch customer IDs for broadcast")
        return []


def record_rider_status(rider_id, rider_name, availability):
    """Set a rider's Online/Offline status in column F, creating the rider row if needed."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            return
        rows = ws.get_all_values()
        if rows and len(rows[0]) < 6:
            ws.update("F1", [["Availability"]])
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 1 and row[1] == str(rider_id):
                ws.update(f"F{idx}", [[availability]])
                return
        # Rider not in sheet yet — add them with zero counts
        ws.append_row([rider_name, str(rider_id), 0, "", 0, availability])
    except Exception:
        logger.exception("Failed to update rider availability")


def get_online_riders():
    """Return a list of rider names currently marked Online."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            return []
        records = ws.get_all_records()
        return [r.get("Rider Name", "Unknown") for r in records if r.get("Availability") == "Online"]
    except Exception:
        logger.exception("Failed to read online riders")
        return []


async def handle_delivered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, customer_id_str = query.data.split(":", 1)

    claimed_orders = context.application.bot_data.get("claimed_orders", {})
    order = claimed_orders.get(customer_id_str)

    if order is None:
        await query.answer("This order's details are no longer available.", show_alert=True)
        return

    if order.get("rider_id") != query.from_user.id:
        await query.answer("Only the rider who claimed this can mark it delivered.", show_alert=True)
        return

    if order.get("delivered"):
        await query.answer("Already marked as delivered.")
        return

    # Ask the rider for a proof photo instead of finalizing immediately
    awaiting = context.application.bot_data.setdefault("awaiting_delivery_proof", {})
    awaiting[query.from_user.id] = customer_id_str

    await query.answer("Almost done!")
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="📸 Please send a photo of the delivered package/drop-off as proof to complete this order.",
    )


async def handle_delivery_proof_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global photo handler — only acts if the sender is a rider currently submitting delivery proof."""
    rider_id = update.effective_user.id
    awaiting = context.application.bot_data.get("awaiting_delivery_proof", {})
    customer_id_str = awaiting.get(rider_id)
    if not customer_id_str:
        return  # not a rider mid-proof-submission — ignore, let other handlers process it

    claimed_orders = context.application.bot_data.get("claimed_orders", {})
    order = claimed_orders.get(customer_id_str)
    if order is None:
        awaiting.pop(rider_id, None)
        return

    awaiting.pop(rider_id, None)
    order["delivered"] = True

    photo_file_id = update.message.photo[-1].file_id
    rider_name = order.get("rider_name", "Your rider")

    await update.message.reply_text("✅ Delivery confirmed! Thanks for the proof — great work 🚴")

    # Forward proof photo + rating request to the customer
    rating_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(str(n), callback_data=f"rate:{n}:{rider_id}:{customer_id_str}")
        for n in range(1, 6)
    ]])
    try:
        await context.bot.send_photo(
            chat_id=order.get("customer_id"),
            photo=photo_file_id,
            caption=(
                "✅ Your BikeBlitz order has been delivered! Thanks for choosing us 🚴\n\n"
                f"How was your rider, {rider_name}? Rate your delivery 👇"
            ),
            reply_markup=rating_keyboard,
        )
    except Exception:
        logger.exception("Could not notify customer of delivery completion")

    # Forward proof to admin too
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file_id,
            caption=f"📦 Delivery proof — {order.get('customer_name')} — ₦{order.get('total', 0):,}",
        )
    except Exception:
        logger.exception("Could not forward delivery proof to admin")

    mark_transaction_delivered(order.get("sheet_row"))
    record_rider_completion(rider_id, order.get("total", 0))


async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, stars_str, rider_id_str, customer_id_str = query.data.split(":", 3)
    stars = int(stars_str)

    claimed_orders = context.application.bot_data.get("claimed_orders", {})
    order = claimed_orders.get(customer_id_str, {})
    customer_name = order.get("customer_name", "A customer")
    rider_name = order.get("rider_name", "Unknown rider")

    record_rating(customer_name, rider_name, rider_id_str, stars)

    await query.answer(f"Thanks for the {stars}⭐ rating!")
    try:
        await query.edit_message_caption(
            caption=(query.message.caption or "") + f"\n\nYou rated this delivery {stars}⭐. Thank you!",
        )
    except Exception:
        pass

    try:
        await context.bot.send_message(
            chat_id=int(rider_id_str),
            text=f"⭐ You just received a {stars}-star rating from {customer_name}!",
        )
    except Exception:
        logger.exception("Could not notify rider of rating")


def get_customer_orders(telegram_id, limit=5):
    """Return a customer's most recent orders (up to limit), most recent first."""
    try:
        sheet = get_sheet()
        if sheet is None:
            return []
        records = sheet.get_all_records()
        matches = [r for r in records if str(r.get("Telegram ID", "")) == str(telegram_id)]
        return list(reversed(matches))[:limit]
    except Exception:
        logger.exception("Failed to fetch customer order history")
        return []


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    order = get_customer_last_order(user.id)
    if order is None:
        await update.message.reply_text(
            "We couldn't find any recent orders for you. Place one from the menu below! 👇",
            reply_markup=main_menu()
        )
        return

    status_text = order.get("Status", "Unknown")
    emoji = "✅" if status_text == "Delivered" else "🚴" if status_text == "Pending" else "❔"
    msg = (
        f"{emoji} *Order Status: {status_text}*\n\n"
        f"🗺️ Zone: {order.get('Zone', 'N/A')}\n"
        f"📍 Location: {order.get('Location', 'N/A')}\n"
        f"💳 Total: ₦{order.get('Total', 0):,}\n"
        f"🕒 Placed: {order.get('Timestamp', 'N/A')}"
    )
    if status_text == "Delivered" and order.get("Delivered At"):
        msg += f"\n✅ Delivered: {order.get('Delivered At')}"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    orders = get_customer_orders(user.id, limit=5)
    if not orders:
        await update.message.reply_text(
            "No past orders found. Place your first one from the menu below! 👇",
            reply_markup=main_menu()
        )
        return

    lines = ["📋 *Your Recent Orders*\n"]
    for o in orders:
        status_emoji = "✅" if o.get("Status") == "Delivered" else "🚴" if o.get("Status") == "Pending" else "❌" if o.get("Status") == "Cancelled" else "❔"
        lines.append(
            f"{status_emoji} {o.get('Timestamp', 'N/A')} — {o.get('Zone', 'N/A')} — "
            f"₦{o.get('Total', 0):,} ({o.get('Status', 'Unknown')})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # silently ignore — this is admin-only

    data = get_todays_stats()
    if data is None:
        await update.message.reply_text("Couldn't load stats right now — try again shortly.")
        return

    msg = (
        "📊 *BikeBlitz Stats*\n\n"
        f"*Today:* {data['today_orders']} orders — ₦{data['today_revenue']:,}\n"
        f"*All-time:* {data['total_orders']} orders — ₦{data['total_revenue']:,}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws = get_riders_sheet()
    if ws is None:
        await update.message.reply_text("📊 Leaderboard isn't set up yet — check back soon!")
        return

    try:
        records = ws.get_all_records()
    except Exception:
        logger.exception("Failed to read Riders worksheet for leaderboard")
        await update.message.reply_text("Couldn't load the leaderboard right now, try again shortly.")
        return

    if not records:
        await update.message.reply_text("🏆 No deliveries logged yet — be the first to claim one!")
        return

    def _count(r):
        try:
            return int(r.get("Deliveries Claimed", 0) or 0)
        except (TypeError, ValueError):
            return 0

    sorted_riders = sorted(records, key=_count, reverse=True)
    top = sorted_riders[:10]

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *BikeBlitz Rider Leaderboard*\n"]
    for i, r in enumerate(top):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        name = r.get("Rider Name", "Unknown")
        count = _count(r)
        lines.append(f"{prefix} {name} — {count} deliver{'y' if count == 1 else 'ies'}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def record_rider_zone(rider_id, rider_name, zone_name):
    """Set a rider's home zone in column H, creating the row/column if needed."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            return
        rows = ws.get_all_values()
        if rows and len(rows[0]) < 8:
            ws.update("H1", [["Home Zone"]])
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > 1 and row[1] == str(rider_id):
                ws.update(f"H{idx}", [[zone_name]])
                return
        ws.append_row([rider_name, str(rider_id), 0, "", 0, "", 0, zone_name])
    except Exception:
        logger.exception("Failed to update rider home zone")


def get_riders_by_zone(zone_name):
    """Return Telegram IDs of online riders whose home zone matches."""
    try:
        ws = get_riders_sheet()
        if ws is None:
            return []
        records = ws.get_all_records()
        return [
            r.get("Telegram ID") for r in records
            if r.get("Home Zone") == zone_name and r.get("Availability") == "Online"
        ]
    except Exception:
        logger.exception("Failed to fetch riders by zone")
        return []


async def online(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    record_rider_status(user.id, user.full_name, "Online")
    await update.message.reply_text("🟢 You're marked as *Online* — you'll be visible for new orders!", parse_mode="Markdown")


async def offline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    record_rider_status(user.id, user.full_name, "Offline")
    await update.message.reply_text("🔴 You're marked as *Offline*. Use /online when you're back!", parse_mode="Markdown")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # admin-only, silently ignore otherwise

    message_text = update.message.text.partition(" ")[2].strip()
    if not message_text:
        await update.message.reply_text(
            "Usage: `/broadcast Your message here` — sends to every past customer.",
            parse_mode="Markdown"
        )
        return

    customer_ids = get_all_customer_ids()
    if not customer_ids:
        await update.message.reply_text("No customers found to broadcast to yet.")
        return

    sent, failed = 0, 0
    for cid in customer_ids:
        try:
            await context.bot.send_message(chat_id=int(cid), text=f"📢 {message_text}")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(f"📤 Broadcast sent to {sent} customers. ({failed} unreachable)")


async def myearnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = get_rider_stats(user.id)
    if stats is None:
        await update.message.reply_text("No delivery history found yet — claim your first order to get started! 🚴")
        return

    completed = stats.get("Completed Deliveries", 0) or 0
    earnings = stats.get("Total Earnings", 0) or 0
    claimed = stats.get("Deliveries Claimed", 0) or 0

    await update.message.reply_text(
        f"💰 *Your BikeBlitz Earnings*\n\n"
        f"📦 Deliveries claimed: {claimed}\n"
        f"✅ Deliveries completed: {completed}\n"
        f"💳 Total earned: ₦{int(earnings):,}",
        parse_mode="Markdown"
    )


async def setzone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    zone_map = {
        "1": "Zone 1 - On Campus",
        "2": "Zone 2 - Near Off Campus",
        "3": "Zone 3 - Mid Off Campus",
        "4": "Zone 4 - Far Off Campus",
    }
    if not context.args or context.args[0] not in zone_map:
        await update.message.reply_text(
            "Set your home zone so you get a heads-up when matching orders come in:\n\n"
            "`/setzone 1` — On Campus\n"
            "`/setzone 2` — Near Off Campus\n"
            "`/setzone 3` — Mid Off Campus\n"
            "`/setzone 4` — Far Off Campus",
            parse_mode="Markdown"
        )
        return

    zone_name = zone_map[context.args[0]]
    user = update.effective_user
    record_rider_zone(user.id, user.full_name, zone_name)
    await update.message.reply_text(
        f"✅ Your home zone is set to *{zone_name}*.\n\n"
        "You'll get a heads-up ping when matching orders come in (as long as you're /online)!",
        parse_mode="Markdown"
    )


async def whosonline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    online_riders = get_online_riders()
    if not online_riders:
        await update.message.reply_text("😴 No riders currently marked online.")
        return
    lines = ["🟢 *Riders Online Now:*\n"] + [f"• {name}" for name in online_riders]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------- Referral & promo commands ----------

async def myreferral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row_idx, row = get_or_create_referral_row(user.id, user.full_name)
    if row_idx is None:
        await update.message.reply_text("Referral system isn't set up yet — check back soon!")
        return
    code = row[2]
    credit = int(row[4]) if len(row) > 4 and str(row[4]).isdigit() else 0
    await update.message.reply_text(
        f"🎁 *Your Referral Code:* `{code}`\n\n"
        "Share it with friends! When they run:\n"
        f"`/referral {code}`\n\n"
        f"• They get ₦{REFERRAL_BONUS_REFERRED} credit\n"
        f"• You get ₦{REFERRAL_BONUS_REFERRER} credit\n\n"
        f"💰 Your current credit balance: ₦{credit:,}\n"
        f"_Credit is applied automatically at checkout, up to {REFERRAL_CREDIT_MAX_PERCENT}% of each order's total._",
        parse_mode="Markdown",
    )


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "Usage: `/referral CODE` — enter a friend's referral code to get credit.",
            parse_mode="Markdown"
        )
        return
    code = context.args[0].upper()
    success, msg = redeem_referral_code(user.id, user.full_name, code)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def createpromo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        return  # admin-only, silently ignore otherwise

    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: `/createpromo CODE TYPE VALUE MAXUSES [EXPIRY]`\n\n"
            "TYPE: `percent` or `fixed`\n"
            "VALUE: number (e.g. 10 for 10% or ₦10)\n"
            "MAXUSES: 0 for unlimited\n"
            "EXPIRY: optional, format YYYY-MM-DD\n\n"
            "Example:\n`/createpromo WELCOME10 percent 10 100 2026-12-31`",
            parse_mode="Markdown"
        )
        return

    code, promo_type, value_str, max_uses_str = context.args[0], context.args[1].lower(), context.args[2], context.args[3]
    expiry = context.args[4] if len(context.args) > 4 else ""

    if promo_type not in ("percent", "fixed"):
        await update.message.reply_text("TYPE must be `percent` or `fixed`.", parse_mode="Markdown")
        return
    try:
        value = int(value_str)
        max_uses = int(max_uses_str)
    except ValueError:
        await update.message.reply_text("VALUE and MAXUSES must be numbers.")
        return

    success, msg = create_promo_code(code, promo_type, value, max_uses, expiry)
    await update.message.reply_text(("✅ " if success else "❌ ") + msg, parse_mode="Markdown")


# ---------- Rider application flow ----------

async def apply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🚴 *Ride for BikeBlitz*\n\n"
        "Thanks for your interest! This takes about 2 minutes — we'll follow up with a quick call after.\n\n"
        "What's your full name?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
    )
    return APPLY_NAME


async def apply_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Application cancelled. Run /apply anytime to start again.",
        reply_markup=main_menu()
    )
    context.user_data.clear()
    return ConversationHandler.END


async def apply_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await apply_cancel(update, context)
    context.user_data["apply_name"] = update.message.text.strip()
    await update.message.reply_text(
        "📱 What's your phone number (WhatsApp preferred)?",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
    )
    return APPLY_PHONE


async def apply_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await apply_cancel(update, context)
    context.user_data["apply_phone"] = update.message.text.strip()
    await update.message.reply_text(
        "🗺️ Which zone do you live in / can mainly ride for?",
        reply_markup=apply_zone_keyboard()
    )
    return APPLY_ZONE


async def apply_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "❌ Cancel":
        return await apply_cancel(update, context)
    if text not in ZONE_PRICES:
        await update.message.reply_text("Please select a valid zone 👇", reply_markup=apply_zone_keyboard())
        return APPLY_ZONE
    context.user_data["apply_zone"] = text
    await update.message.reply_text(
        "🚲 Tell us about your bike — type and condition.\n\n"
        "_Example: Pedal bike, good condition, new tires_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
    )
    return APPLY_BIKE


async def apply_bike(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await apply_cancel(update, context)
    context.user_data["apply_bike"] = update.message.text.strip()
    await update.message.reply_text(
        "🕒 What days/hours can you ride?\n\n"
        "_Example: Weekdays 4pm-9pm, weekends flexible_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
    )
    return APPLY_AVAILABILITY


async def apply_availability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await apply_cancel(update, context)
    context.user_data["apply_availability"] = update.message.text.strip()
    await update.message.reply_text(
        "🧠 Last one — a quick judgment question:\n\n"
        "_You arrive to pick up an errand item, and it costs ₦500 more than the customer told you. "
        "What do you do?_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
    )
    return APPLY_JUDGMENT


async def apply_judgment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ Cancel":
        return await apply_cancel(update, context)
    context.user_data["apply_judgment"] = update.message.text.strip()

    user = update.effective_user
    name = context.user_data.get("apply_name", user.full_name)
    phone = context.user_data.get("apply_phone", "N/A")
    zone = context.user_data.get("apply_zone", "N/A")
    bike = context.user_data.get("apply_bike", "N/A")
    availability = context.user_data.get("apply_availability", "N/A")
    judgment = context.user_data.get("apply_judgment", "")

    row = save_application(user.id, name, phone, zone, bike, availability, judgment)

    pending = context.application.bot_data.setdefault("pending_applications", {})
    pending[str(user.id)] = {
        "name": name,
        "phone": phone,
        "zone": zone,
        "bike": bike,
        "availability": availability,
        "judgment": judgment,
        "row": row,
    }

    summary = (
        "🚴 *New Rider Application*\n\n"
        f"👤 Name: {name}\n"
        f"🆔 Telegram: @{user.username or 'no username'} (ID {user.id})\n"
        f"📱 Phone: {phone}\n"
        f"🗺️ Zone: {zone}\n"
        f"🚲 Bike: {bike}\n"
        f"🕒 Availability: {availability}\n\n"
        f"🧠 Judgment answer:\n_{judgment}_"
    )
    decision_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"riderapprove:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"riderreject:{user.id}"),
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=summary,
        parse_mode="Markdown",
        reply_markup=decision_keyboard,
    )

    await update.message.reply_text(
        "✅ Application received! We'll follow up with a quick call, then let you know here.\n\n"
        "Thanks for wanting to ride with BikeBlitz! 🚴",
        reply_markup=main_menu()
    )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_rider_application_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, applicant_id_str = query.data.split(":", 1)
    applicant_id = int(applicant_id_str)

    pending = context.application.bot_data.get("pending_applications", {})
    app_info = pending.pop(applicant_id_str, None)

    if action == "riderapprove":
        name = app_info.get("name", "Unknown") if app_info else "Unknown"
        zone = app_info.get("zone") if app_info else None
        row = app_info.get("row") if app_info else None

        update_application_status(row, "Approved")
        if zone:
            record_rider_zone(applicant_id, name, zone)

        await query.edit_message_text(
            (query.message.text or "") + "\n\n✅ *APPROVED*",
            parse_mode="Markdown",
        )
        try:
            await context.bot.send_message(
                chat_id=applicant_id,
                text=(
                    "🎉 *You're in!* Welcome to the BikeBlitz rider team.\n\n"
                    "Quick commands to know:\n"
                    "`/online` — mark yourself available for orders\n"
                    "`/offline` — step away\n"
                    "`/setzone` — set/update your home zone\n"
                    "`/myearnings` — check your earnings\n"
                    "`/leaderboard` — see top riders\n\n"
                    "Run `/online` whenever you're ready to start riding! 🚴"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Could not notify approved applicant")
    else:
        row = app_info.get("row") if app_info else None
        update_application_status(row, "Rejected")
        await query.edit_message_text(
            (query.message.text or "") + "\n\n❌ *REJECTED*",
            parse_mode="Markdown",
        )
        try:
            await context.bot.send_message(
                chat_id=applicant_id,
                text=(
                    "Thanks for your interest in BikeBlitz. We're not able to bring you on right now, "
                    "but we'll keep your info on file for future openings."
                ),
            )
        except Exception:
            logger.exception("Could not notify rejected applicant")


async def handle_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, customer_id_str = query.data.split(":", 1)

    claimed_orders = context.application.bot_data.get("claimed_orders", {})
    order = claimed_orders.get(customer_id_str)

    if order is None:
        await query.answer("This order can no longer be cancelled.", show_alert=True)
        return

    if order.get("delivered"):
        await query.answer("This order has already been delivered and can't be cancelled.", show_alert=True)
        return

    if order.get("cancelled"):
        await query.answer("Already cancelled.")
        return

    order["cancelled"] = True
    await query.answer("Order cancelled.")

    await query.edit_message_text(
        (query.message.text or "") + "\n\n❌ *ORDER CANCELLED*",
        parse_mode="Markdown",
    )

    # Update the sheet status
    try:
        sheet = get_sheet()
        row = order.get("sheet_row")
        if sheet and row:
            sheet.update(f"I{row}", [["Cancelled"]])
    except Exception:
        logger.exception("Failed to update cancelled status in sheet")

    # Notify admin — a refund likely needs manual handling
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"⚠️ *Order Cancelled by Customer*\n\n"
                f"👤 {order.get('customer_name')}\n"
                f"💳 ₦{order.get('total', 0):,}\n\n"
                f"A refund may need to be processed manually."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Failed to notify admin of cancellation")

    # If a rider had already claimed it, let them know it's off
    rider_id = order.get("rider_id")
    if rider_id:
        try:
            await context.bot.send_message(
                chat_id=rider_id,
                text="❌ This delivery was cancelled by the customer. No action needed — sorry for the trouble!",
            )
        except Exception:
            logger.exception("Failed to notify rider of cancellation")

    # If not yet claimed, remove the button from the rider group broadcast
    broadcast_id = order.get("broadcast_message_id")
    if broadcast_id and not rider_id:
        try:
            await context.bot.edit_message_text(
                chat_id=RIDER_GROUP_CHAT_ID,
                message_id=broadcast_id,
                text="❌ This order was cancelled by the customer before being claimed.",
            )
        except Exception:
            logger.exception("Failed to update rider group broadcast after cancellation")


async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(
        f"Chat ID: `{chat.id}`\nChat type: {chat.type}",
        parse_mode="Markdown"
    )




async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    last_order = get_customer_last_order(user.id)

    if last_order:
        last_zone = last_order.get("Zone", "")
        greeting = (
            f"👋 Welcome back to *BikeBlitz*, {user.first_name}! 🚴\n\n"
            f"Last time you ordered in *{last_zone}* — same zone today, or something new?\n\n"
        )
    else:
        greeting = (
            "👋 Welcome to *BikeBlitz* 🚴\n\n"
            "FUNAAB's fastest campus delivery and errand service.\n\n"
        )

    await update.message.reply_text(
        greeting +
        "🕒 *Operating Hours:* Daily 9am – 9pm\n"
        "🌙 *Same-day cut-off:* 8pm\n\n"
        "Fast. Reliable. Zero silence. Every order.\n\n"
        "What would you like to do today? 👇",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    return CHOOSING_SERVICE


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *About BikeBlitz*\n\n"
        "BikeBlitz is a student-powered campus delivery and errand service based at FUNAAB, Abeokuta.\n\n"
        "We handle:\n"
        "📦 Package and document delivery\n"
        "🛒 Errands and market runs\n"
        "🍔 Food pickup and delivery\n\n"
        "Our riders are FUNAAB students who know the campus inside out.\n\n"
        "Fast. Reliable. Community-driven. 🚴",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    return CHOOSING_SERVICE


async def zones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🗺️ *BikeBlitz Delivery Zones*\n\n"
        "📍 *Zone 1 — On Campus*\n"
        "Anywhere within FUNAAB campus\n\n"
        "📍 *Zone 2 — Near Off Campus*\n"
        "Harmony, Accord, Zoo, Agbede, Kofesu\n\n"
        "📍 *Zone 3 — Mid Off Campus*\n"
        "Labuta, Isolu-Cele, Isolu-FUNIS, Camp\n\n"
        "📍 *Zone 4 — Far Off Campus*\n"
        "Town\n\n"
        "_Note: A ₦200 distance modifier applies if your location is far from the main bus stop._"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())
    return CHOOSING_SERVICE


async def pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💰 *BikeBlitz Price List*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "*B2B — Package Delivery*\n"
        "━━━━━━━━━━━━━━━━\n"
        "Zone 1: Light ₦300 | Medium ₦500 | Heavy ₦700\n"
        "Zone 2: Light ₦500 | Medium ₦700 | Heavy ₦900\n"
        "Zone 3: Light ₦700 | Medium ₦900 | Heavy ₦1,100\n"
        "Zone 4: Light ₦1,200 | Medium ₦1,400 | Heavy ₦1,600\n\n"
        "📍 Far from bus stop: +₦200\n"
        "⚡ Express delivery: +₦300\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "*B2C — Errands & Food*\n"
        "━━━━━━━━━━━━━━━━\n"
        "Zone fee + Service fee = Total charge\n\n"
        "Simple errand/food: +₦100\n"
        "Complex errand/bulk shopping: +₦250\n\n"
        "_Item cost is paid directly to vendor._\n\n"
        "⚖️ *Weight Guide:*\n"
        "Light = fits in one hand\n"
        "Medium = requires two hands\n"
        "Heavy = requires effort to carry\n"
        "Very Heavy = 10kg+ (negotiated)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())
    return CHOOSING_SERVICE


async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 *Payment Information*\n\n"
        "BikeBlitz requires payment of the delivery charge *before* your rider moves.\n\n"
        "📝 *How it works:*\n"
        "1️⃣ Place your order\n"
        "2️⃣ Receive your price quote\n"
        "3️⃣ Transfer the delivery charge to our account\n"
        "4️⃣ Send your receipt screenshot to confirm\n"
        "5️⃣ Your rider moves immediately ⚡\n\n"
        "🏦 *Bank Details:*\n"
        "Bank: Moniepoint\n"
        "Account Number: 8144124522\n"
        "Account Name: Lawal Abdussalam\n\n"
        "_For B2C orders: item cost is paid directly by you to the vendor when your rider arrives._",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    return CHOOSING_SERVICE


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *Contact BikeBlitz*\n\n"
        "Need to speak to a team member directly?\n\n"
        "📱 WhatsApp: 08144124522\n"
        "📧 Email: lawalabdussalam47@gmail.com\n"
        "📍 Location: FUNAAB Campus, Abeokuta\n\n"
        "🕒 Available daily 9am – 9pm\n\n"
        "_For orders and quotes, use the menu below for faster service._",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )
    return CHOOSING_SERVICE


# ---------- B2B / B2C flows ----------

async def b2b_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["service"] = "B2B"
    context.user_data["delivery_type"] = "Standard"
    await update.message.reply_text(
        "📦 *Package Delivery*\n\n"
        "Let's get your package delivered!\n\n"
        "First, select your delivery zone 👇\n\n"
        "Not sure which zone? Use /zones to check.",
        parse_mode="Markdown",
        reply_markup=zone_keyboard()
    )
    return CHOOSING_ZONE


async def b2c_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["service"] = "B2C"
    context.user_data["delivery_type"] = "Standard"
    await update.message.reply_text(
        "🛒 *Errand / Food / Market Run*\n\n"
        "We'll go buy or collect it for you!\n\n"
        "First, what type of errand is this? 👇",
        parse_mode="Markdown",
        reply_markup=errand_keyboard()
    )
    return CHOOSING_ERRAND


async def express_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["delivery_type"] = "Express"
    await update.message.reply_text(
        "⚡ *Express Delivery*\n\n"
        "Need it done urgently? We've got you!\n\n"
        "Express delivery adds *₦300* on top of your zone price for priority handling.\n\n"
        "Is this a package delivery or an errand? 👇",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("📦 Package Delivery")],
            [KeyboardButton("🛒 Errand / Food / Market")],
            [KeyboardButton("🏠 Main Menu")],
        ], resize_keyboard=True)
    )
    return CHOOSING_SERVICE


async def schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["delivery_type"] = "Scheduled"
    await update.message.reply_text(
        "📅 *Schedule a Delivery*\n\n"
        "Plan ahead and we'll handle it at your preferred time!\n\n"
        "📝 *Rules:*\n"
        "• Minimum 1 hour notice required\n"
        "• Same-day scheduling closes at 8pm\n"
        "• Available daily 9am – 9pm\n\n"
        "Please type your preferred date and time:\n"
        "_(Example: Tomorrow 2pm or Monday 10am)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
    )
    return SCHEDULING_TIME


async def handle_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    scheduled_time = update.message.text
    context.user_data["scheduled_time"] = scheduled_time
    await update.message.reply_text(
        f"✅ Got it! Scheduled for: *{scheduled_time}*\n\n"
        "Now, is this a package delivery or an errand? 👇",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("📦 Package Delivery")],
            [KeyboardButton("🛒 Errand / Food / Market")],
            [KeyboardButton("🏠 Main Menu")],
        ], resize_keyboard=True)
    )
    return CHOOSING_SERVICE


async def handle_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    if text not in ZONE_PRICES:
        await update.message.reply_text("Please select a valid zone 👇", reply_markup=zone_keyboard())
        return CHOOSING_ZONE

    context.user_data["zone"] = text
    service = context.user_data.get("service", "B2B")

    if service == "B2B":
        await update.message.reply_text(
            f"✅ Zone selected: *{text}*\n\n"
            "Now, how heavy is your package? 👇",
            parse_mode="Markdown",
            reply_markup=weight_keyboard()
        )
        return CHOOSING_WEIGHT
    else:
        await update.message.reply_text(
            f"✅ Zone selected: *{text}*\n\n"
            "Is your pickup/dropoff location close to the main bus stop or far from it? 👇",
            parse_mode="Markdown",
            reply_markup=busstop_keyboard()
        )
        return CHOOSING_BUSSTOP


async def handle_errand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    if text not in ERRAND_FEES:
        await update.message.reply_text("Please select a valid errand type 👇", reply_markup=errand_keyboard())
        return CHOOSING_ERRAND

    context.user_data["errand_type"] = text
    context.user_data["errand_fee"] = ERRAND_FEES[text]

    await update.message.reply_text(
        f"✅ Errand type: *{text}*\n\n"
        "What exactly do you need us to get or do? Be specific (items, quantities, restaurant/shop name, etc.)\n\n"
        "_Example: 2 loaves of bread and a carton of eggs from Mama Nkechi's shop near Zoo gate_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
    )
    return AWAITING_ERRAND_ITEMS


async def handle_errand_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    context.user_data["errand_items"] = text.strip()

    await update.message.reply_text(
        f"📝 Got it: *{text.strip()}*\n\n"
        "Now select your delivery zone 👇",
        parse_mode="Markdown",
        reply_markup=zone_keyboard()
    )
    return CHOOSING_ZONE


async def handle_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    weight = parse_weight(text)
    if not weight:
        await update.message.reply_text("Please select a valid weight 👇", reply_markup=weight_keyboard())
        return CHOOSING_WEIGHT

    if weight == "Very Heavy":
        await update.message.reply_text(
            "⚖️ *Very Heavy Package*\n\n"
            "Packages above 10kg need to be negotiated separately.\n\n"
            "Please contact us directly:\n"
            "📱 WhatsApp: 08144124522\n\n"
            "We'll get back to you immediately! ⚡",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )
        return CHOOSING_SERVICE

    context.user_data["weight"] = weight
    await update.message.reply_text(
        f"✅ Weight: *{weight}*\n\n"
        "Is your dropoff location close to the main bus stop or far from it? 👇",
        parse_mode="Markdown",
        reply_markup=busstop_keyboard()
    )
    return CHOOSING_BUSSTOP


async def handle_busstop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    far_from_busstop = "Far" in text
    context.user_data["far_from_busstop"] = far_from_busstop

    user = update.effective_user
    last_order = get_customer_last_order(user.id)
    last_location = last_order.get("Location") if last_order else None

    keyboard_rows = []
    if last_location:
        keyboard_rows.append([KeyboardButton(f"📍 Use last: {last_location}")])
    keyboard_rows.append([KeyboardButton("🏠 Main Menu")])

    await update.message.reply_text(
        "📝 One last thing — please describe your *exact location* within the zone "
        "(hostel/building name, house number, nearest landmark, etc.) so your rider "
        "can find you door-to-door.\n\n"
        "_Example: Alpha Hostel, Room 14, behind the FUNAAB clinic_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True)
    )
    return CHOOSING_LOCATION_DETAILS


async def handle_location_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)
    if text.startswith("📍 Use last: "):
        text = text[len("📍 Use last: "):]

    context.user_data["location_details"] = text.strip()

    far_from_busstop = context.user_data.get("far_from_busstop", False)
    zone = context.user_data.get("zone")
    service = context.user_data.get("service", "B2B")
    delivery_type = context.user_data.get("delivery_type", "Standard")
    location_details = context.user_data.get("location_details", "")

    if service == "B2B":
        weight = context.user_data.get("weight")
        base_price = ZONE_PRICES[zone][weight]
        distance_add = DISTANCE_MODIFIER if far_from_busstop else 0
        express_add = EXPRESS_SURCHARGE if delivery_type == "Express" else 0
        total = base_price + distance_add + express_add

        breakdown = (
            f"📋 *Order Summary*\n\n"
            f"📦 Service: Package Delivery\n"
            f"🗺️ Zone: {zone}\n"
            f"📍 Location: {location_details}\n"
            f"⚖️ Weight: {weight}\n"
            f"🚴 Delivery Type: {delivery_type}\n"
            f"📍 Far from bus stop: {'Yes' if far_from_busstop else 'No'}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 Base price: ₦{base_price:,}\n"
        )
        if distance_add:
            breakdown += f"📍 Distance modifier: +₦{distance_add:,}\n"
        if express_add:
            breakdown += f"⚡ Express surcharge: +₦{express_add:,}\n"
    else:
        errand_fee = context.user_data.get("errand_fee", 100)
        errand_type = context.user_data.get("errand_type")
        errand_items = context.user_data.get("errand_items", "N/A")
        base_price = ZONE_PRICES[zone]["Light"]
        distance_add = DISTANCE_MODIFIER if far_from_busstop else 0
        express_add = EXPRESS_SURCHARGE if delivery_type == "Express" else 0
        total = base_price + errand_fee + distance_add + express_add

        breakdown = (
            f"📋 *Order Summary*\n\n"
            f"🛒 Service: {errand_type}\n"
            f"📝 Items: {errand_items}\n"
            f"🗺️ Zone: {zone}\n"
            f"📍 Location: {location_details}\n"
            f"🚴 Delivery Type: {delivery_type}\n"
            f"📍 Far from bus stop: {'Yes' if far_from_busstop else 'No'}\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 Zone delivery fee: ₦{base_price:,}\n"
            f"🛍️ Service fee: ₦{errand_fee:,}\n"
        )
        if distance_add:
            breakdown += f"📍 Distance modifier: +₦{distance_add:,}\n"
        if express_add:
            breakdown += f"⚡ Express surcharge: +₦{express_add:,}\n"

    context.user_data["base_price"] = base_price
    context.user_data["distance_add"] = distance_add
    context.user_data["express_add"] = express_add

    # Auto-apply any referral credit the customer has earned, capped per order
    user_id = update.effective_user.id
    credit = get_credit_balance(user_id)
    credit_cap = int(total * REFERRAL_CREDIT_MAX_PERCENT / 100)
    credit_applied = min(credit, credit_cap) if credit else 0
    context.user_data["credit_applied"] = credit_applied
    if credit_applied:
        total -= credit_applied
        remaining_credit = credit - credit_applied
        breakdown += f"🎁 Referral credit applied: -₦{credit_applied:,} (max {REFERRAL_CREDIT_MAX_PERCENT}% per order)\n"
        if remaining_credit:
            breakdown += f"_₦{remaining_credit:,} credit remains for a future order_\n"

    context.user_data["total"] = total

    if service == "B2B":
        breakdown += (
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 *Total Delivery Charge: ₦{total:,}*\n\n"
            f"Rider earns: ₦{int(total * 0.7):,} (70%)\n"
            f"BikeBlitz: ₦{int(total * 0.3):,} (30%)\n\n"
            f"Have a promo code? Tap 🎟️ below, or confirm to proceed 👇"
        )
    else:
        breakdown += (
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 *Total Delivery Charge: ₦{total:,}*\n\n"
            f"_Item cost paid directly to vendor_\n\n"
            f"Have a promo code? Tap 🎟️ below, or confirm to proceed 👇"
        )

    if delivery_type == "Scheduled":
        scheduled_time = context.user_data.get("scheduled_time", "")
        breakdown += f"\n📅 Scheduled for: *{scheduled_time}*"

    await update.message.reply_text(breakdown, parse_mode="Markdown", reply_markup=confirm_keyboard())
    return CONFIRMING_ORDER


async def handle_promo_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    code = text.strip().upper()
    valid, promo_type, value, msg = validate_promo_code(code)
    if not valid:
        await update.message.reply_text(
            f"{msg}\n\nTry a different code, or tap ✅ Confirm Order to proceed without one.",
            reply_markup=confirm_keyboard()
        )
        return CONFIRMING_ORDER

    subtotal = context.user_data.get("total", 0)
    if promo_type == "percent":
        discount = int(subtotal * value / 100)
    else:
        discount = min(value, subtotal)

    context.user_data["promo_code"] = code
    context.user_data["promo_discount"] = discount
    new_total = max(0, subtotal - discount)
    context.user_data["total"] = new_total

    await update.message.reply_text(
        f"✅ Promo code *{code}* applied! -₦{discount:,}\n\n"
        f"💳 *New Total: ₦{new_total:,}*\n\n"
        "Ready to confirm? 👇",
        parse_mode="Markdown",
        reply_markup=confirm_keyboard()
    )
    return CONFIRMING_ORDER


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu" or text == "❌ Cancel Order":
        await update.message.reply_text(
            "❌ Order cancelled.\n\nNo worries — start a new order anytime! 🚴",
            reply_markup=main_menu()
        )
        context.user_data.clear()
        return CHOOSING_SERVICE

    if text == "🎟️ Apply Promo Code":
        await update.message.reply_text(
            "🎟️ Enter your promo code:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
        )
        return AWAITING_PROMO_CODE

    if text == "✅ Confirm Order":
        total = context.user_data.get("total", 0)
        delivery_type = context.user_data.get("delivery_type", "Standard")
        scheduled_time = context.user_data.get("scheduled_time", "")
        zone = context.user_data.get("zone")
        service = context.user_data.get("service")

        # Duplicate-order protection — catch accidental double submissions
        user_id = update.effective_user.id
        recent = context.application.bot_data.setdefault("recent_confirmations", {})
        prev = recent.get(user_id)
        if prev and not context.user_data.get("duplicate_confirmed"):
            prev_time, prev_zone, prev_service, prev_total = prev
            if (datetime.now() - prev_time).total_seconds() < 90 and prev_zone == zone and prev_service == service and prev_total == total:
                context.user_data["duplicate_confirmed"] = True
                await update.message.reply_text(
                    "⚠️ You just placed a very similar order less than 2 minutes ago.\n\n"
                    "Tap *✅ Confirm Order* again if this is intentional (e.g. a second package).",
                    parse_mode="Markdown",
                    reply_markup=confirm_keyboard()
                )
                return CONFIRMING_ORDER
        recent[user_id] = (datetime.now(), zone, service, total)

        # Settle referral credit and promo code usage now that the order is truly confirmed
        credit_applied = context.user_data.get("credit_applied", 0)
        if credit_applied:
            deduct_credit(user_id, credit_applied)
        promo_code = context.user_data.get("promo_code")
        if promo_code:
            increment_promo_usage(promo_code)

        confirmation = (
            f"✅ *Order Confirmed!*\n\n"
            f"💳 *Total Delivery Charge: ₦{total:,}*\n\n"
        )
        if credit_applied:
            confirmation += f"🎁 Referral credit applied: -₦{credit_applied:,}\n"
        if context.user_data.get("promo_discount"):
            confirmation += f"🎟️ Promo code {promo_code} applied: -₦{context.user_data.get('promo_discount'):,}\n"
        confirmation += (
            f"\nPlease transfer ₦{total:,} to:\n"
            f"🏦 Bank: Moniepoint\n"
            f"🔢 Account: 8144124522\n"
            f"👤 Name: Lawal Abdussalam\n\n"
            f"After payment:\n"
            f"1️⃣ Send your receipt screenshot here\n"
            f"2️⃣ Your rider will be dispatched immediately ⚡\n\n"
        )
        if delivery_type == "Scheduled":
            confirmation += f"📅 Your delivery is scheduled for: *{scheduled_time}*\n\n"
        confirmation += (
            f"📞 Questions? Contact us:\n"
            f"WhatsApp: 08144124522\n\n"
            f"Thank you for choosing BikeBlitz! 🚴"
        )

        await update.message.reply_text(
            confirmation,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
        )
        return AWAITING_PAYMENT_PROOF

    await update.message.reply_text("Please confirm or cancel the order 👇", reply_markup=confirm_keyboard())
    return CONFIRMING_ORDER


async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 Main Menu":
        return await start(update, context)

    if not update.message.photo:
        await update.message.reply_text(
            "Please send your payment receipt as a *photo/screenshot* 📸, "
            "or tap Main Menu to start over.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
        )
        return AWAITING_PAYMENT_PROOF

    # Build an order summary to send alongside the screenshot
    user = update.effective_user
    zone = context.user_data.get("zone", "N/A")
    service = context.user_data.get("service", "N/A")
    delivery_type = context.user_data.get("delivery_type", "Standard")
    total = context.user_data.get("total", 0)
    weight = context.user_data.get("weight")
    errand_type = context.user_data.get("errand_type")
    errand_items = context.user_data.get("errand_items", "")
    scheduled_time = context.user_data.get("scheduled_time", "")
    location_details = context.user_data.get("location_details", "Not provided")
    promo_code = context.user_data.get("promo_code")
    credit_applied = context.user_data.get("credit_applied", 0)

    summary = (
        f"💰 *New Payment Received*\n\n"
        f"👤 Customer: {user.full_name} (@{user.username or 'no username'})\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"🛠️ Service: {service} {f'- {weight}' if weight else ''}{f'- {errand_type}' if errand_type else ''}\n"
    )
    if errand_items:
        summary += f"📝 Items: {errand_items}\n"
    summary += (
        f"🗺️ Zone: {zone}\n"
        f"📍 Exact location: {location_details}\n"
        f"🚴 Delivery Type: {delivery_type}\n"
    )
    if scheduled_time:
        summary += f"📅 Scheduled: {scheduled_time}\n"
    if credit_applied:
        summary += f"🎁 Referral credit used: ₦{credit_applied:,}\n"
    if promo_code:
        summary += f"🎟️ Promo code used: {promo_code} (-₦{context.user_data.get('promo_discount', 0):,})\n"
    summary += f"💳 Total: ₦{total:,}"

    # Forward the screenshot + summary to the admin, with Approve/Reject buttons
    photo_file_id = update.message.photo[-1].file_id

    # Stash order info so the approve/reject handler can message the right customer
    # and log the transaction once approved
    pending = context.application.bot_data.setdefault("pending_orders", {})
    pending[str(user.id)] = {
        "customer_name": user.full_name,
        "customer_username": user.username,
        "total": total,
        "delivery_type": delivery_type,
        "scheduled_time": scheduled_time,
        "service": service,
        "zone": zone,
        "location": location_details,
        "errand_items": context.user_data.get("errand_items", ""),
    }

    approval_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{user.id}"),
        ]
    ])

    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo_file_id,
        caption=summary,
        parse_mode="Markdown",
        reply_markup=approval_keyboard,
    )

    await update.message.reply_text(
        "📸 Screenshot received!\n\n"
        "We're verifying your payment now — you'll get a confirmation shortly ⏳",
        reply_markup=main_menu()
    )
    context.user_data.clear()
    return CHOOSING_SERVICE


async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, customer_id_str = query.data.split(":", 1)
    customer_id = int(customer_id_str)

    pending = context.application.bot_data.get("pending_orders", {})
    order = pending.pop(customer_id_str, None)

    if action == "approve":
        customer_name = order.get("customer_name", "Unknown") if order else "Unknown"
        customer_username = order.get("customer_username") if order else None
        total = order.get("total", 0) if order else 0
        delivery_type = order.get("delivery_type", "Standard") if order else "Standard"
        scheduled_time = order.get("scheduled_time", "") if order else ""
        service = order.get("service", "N/A") if order else "N/A"
        zone = order.get("zone", "N/A") if order else "N/A"
        location = order.get("location", "N/A") if order else "N/A"
        errand_items = order.get("errand_items", "") if order else ""

        msg = (
            "✅ *Payment Confirmed!*\n\n"
            f"Your delivery charge of ₦{total:,} has been verified.\n\n"
            "Your rider will be dispatched immediately ⚡\n\n"
        )
        if delivery_type == "Scheduled" and scheduled_time:
            msg += f"📅 Your delivery is scheduled for: *{scheduled_time}*\n\n"
        msg += "Thank you for choosing BikeBlitz! 🚴"

        cancel_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel Order", callback_data=f"cancelorder:{customer_id}")]
        ])
        await context.bot.send_message(chat_id=customer_id, text=msg, parse_mode="Markdown", reply_markup=cancel_keyboard)
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n✅ *APPROVED*",
            parse_mode="Markdown",
        )

        sheet_row = log_transaction(
            customer_name=customer_name,
            telegram_id=customer_id,
            service=service,
            zone=zone,
            location=location,
            delivery_type=delivery_type,
            total=total,
        )

        # Stash order details for the claim handler, then broadcast to riders
        claimed_orders = context.application.bot_data.setdefault("claimed_orders", {})
        claimed_orders[customer_id_str] = {
            "customer_name": customer_name,
            "customer_username": customer_username,
            "customer_id": customer_id,
            "service": service,
            "zone": zone,
            "location": location,
            "errand_items": errand_items,
            "delivery_type": delivery_type,
            "scheduled_time": scheduled_time,
            "total": total,
            "rider_id": None,
            "rider_name": None,
            "sheet_row": sheet_row,
            "delivered": False,
        }

        order_text = (
            "🚴 *New Order Available!*\n\n"
            f"🛠️ Service: {service}\n"
        )
        if errand_items:
            order_text += f"📝 Items: {errand_items}\n"
        order_text += (
            f"🗺️ Zone: {zone}\n"
            f"📍 Location: {location}\n"
            f"🚴 Delivery Type: {delivery_type}\n"
        )
        if scheduled_time:
            order_text += f"📅 Scheduled: {scheduled_time}\n"
        order_text += f"💳 Total: ₦{total:,}\n"
        order_text += f"👤 Rider earns: ₦{int(total * 0.7):,} (70%)\n\n"
        order_text += "First to accept gets this delivery 👇"

        claim_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Accept", callback_data=f"claim:{customer_id}")]
        ])

        try:
            broadcast_msg = await context.bot.send_message(
                chat_id=RIDER_GROUP_CHAT_ID,
                text=order_text,
                parse_mode="Markdown",
                reply_markup=claim_keyboard,
            )
            claimed_orders[customer_id_str]["broadcast_message_id"] = broadcast_msg.message_id

            if context.job_queue is not None:
                context.job_queue.run_once(
                    check_unclaimed_order,
                    when=timedelta(minutes=UNCLAIMED_ALERT_MINUTES),
                    data=customer_id_str,
                    name=f"unclaimed_{customer_id_str}",
                )

            # Zone-targeted heads-up — nudge online riders whose home zone matches
            for rider_tid in get_riders_by_zone(zone):
                try:
                    await context.bot.send_message(
                        chat_id=int(rider_tid),
                        text=f"🎯 New order in your zone ({zone})! Check the rider group to claim it.",
                    )
                except Exception:
                    logger.exception(f"Could not send zone heads-up to rider {rider_tid}")
        except Exception:
            logger.exception("Failed to broadcast order to rider group")
    else:
        await context.bot.send_message(
            chat_id=customer_id,
            text=(
                "⚠️ We couldn't verify your payment screenshot.\n\n"
                "Please resend a clear screenshot of your transfer, or contact us:\n"
                "📱 WhatsApp: 08144124522"
            ),
        )
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n❌ *REJECTED*",
            parse_mode="Markdown",
        )


async def check_unclaimed_order(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job — fires if an order sits unclaimed past the alert threshold."""
    customer_id_str = context.job.data
    claimed_orders = context.application.bot_data.get("claimed_orders", {})
    order = claimed_orders.get(customer_id_str)

    if order is None:
        return  # order data is gone entirely, nothing to do
    if order.get("rider_id") or order.get("cancelled") or order.get("delivered"):
        return  # already handled, no action needed

    zone = order.get("zone", "N/A")
    location = order.get("location", "N/A")
    total = order.get("total", 0)

    # Ping the rider group again, referencing the original broadcast if possible
    alert_text = (
        f"⏰ *Still Unclaimed!* This order has been waiting {UNCLAIMED_ALERT_MINUTES}+ minutes.\n\n"
        f"🗺️ Zone: {zone}\n"
        f"📍 Location: {location}\n"
        f"💳 Total: ₦{total:,}\n\n"
        "Can anyone take this? 🙏"
    )
    try:
        broadcast_id = order.get("broadcast_message_id")
        await context.bot.send_message(
            chat_id=RIDER_GROUP_CHAT_ID,
            text=alert_text,
            parse_mode="Markdown",
            reply_to_message_id=broadcast_id if broadcast_id else None,
        )
    except Exception:
        logger.exception("Failed to send unclaimed-order reminder to rider group")

    # Let the admin know directly, in case manual intervention is needed
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"⚠️ *Order Unclaimed After {UNCLAIMED_ALERT_MINUTES} Minutes*\n\n"
                f"👤 {order.get('customer_name')}\n"
                f"🗺️ {zone} — {location}\n"
                f"💳 ₦{total:,}\n\n"
                "You may want to check in with riders directly."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Failed to alert admin of unclaimed order")


async def handle_rider_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    _, customer_id_str = query.data.split(":", 1)
    claimed_orders = context.application.bot_data.get("claimed_orders", {})
    order = claimed_orders.get(customer_id_str)

    if order is None:
        await query.answer("This order no longer exists.", show_alert=True)
        return

    if order.get("rider_id") is not None:
        await query.answer(f"Already claimed by {order.get('rider_name')}.", show_alert=True)
        return

    rider = query.from_user
    order["rider_id"] = rider.id
    order["rider_name"] = rider.full_name

    record_rider_delivery(rider.id, rider.full_name)

    await query.answer("You've got this delivery! Check your DM for details.")

    await query.edit_message_text(
        (query.message.text or "") + f"\n\n✅ *Claimed by {rider.full_name}*",
        parse_mode="Markdown",
    )

    customer_username = order.get("customer_username")
    customer_contact = f"@{customer_username}" if customer_username else f"Telegram ID {order.get('customer_id')}"

    detail_text = (
        "📦 *Delivery Details*\n\n"
        f"🛠️ Service: {order.get('service')}\n"
    )
    if order.get("errand_items"):
        detail_text += f"📝 Items: {order.get('errand_items')}\n"
    detail_text += (
        f"🗺️ Zone: {order.get('zone')}\n"
        f"📍 Location: {order.get('location')}\n"
        f"🚴 Delivery Type: {order.get('delivery_type')}\n"
    )
    if order.get("scheduled_time"):
        detail_text += f"📅 Scheduled: {order.get('scheduled_time')}\n"
    detail_text += (
        f"💳 Total: ₦{order.get('total', 0):,}\n"
        f"👤 Customer: {order.get('customer_name')} ({customer_contact})\n\n"
        "Please reach out to the customer to confirm pickup/drop-off. Ride safe! 🚴"
    )

    delivered_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Mark as Delivered", callback_data=f"delivered:{customer_id_str}")]
    ])

    try:
        await context.bot.send_message(
            chat_id=rider.id, text=detail_text, parse_mode="Markdown", reply_markup=delivered_keyboard
        )
    except Exception:
        logger.exception("Could not DM rider — they may not have started the bot yet")

    # Let the customer know a rider has been assigned
    try:
        await context.bot.send_message(
            chat_id=order.get("customer_id"),
            text=f"🚴 Your rider *{rider.full_name}* has been assigned and will reach out shortly!",
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Could not notify customer of rider assignment")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🏠 Main Menu":
        return await start(update, context)
    elif text in ("📦 Send a Package", "📦 Package Delivery"):
        context.user_data["service"] = "B2B"
        if not context.user_data.get("delivery_type"):
            context.user_data["delivery_type"] = "Standard"
        await update.message.reply_text(
            "📦 *Package Delivery*\n\nSelect your delivery zone 👇",
            parse_mode="Markdown",
            reply_markup=zone_keyboard()
        )
        return CHOOSING_ZONE
    elif text in ("🛒 Errand / Food / Market", "🛒 Errand / Food / Market Run"):
        context.user_data["service"] = "B2C"
        if not context.user_data.get("delivery_type"):
            context.user_data["delivery_type"] = "Standard"
        await update.message.reply_text(
            "🛒 *Errand / Food / Market Run*\n\nWhat type of errand? 👇",
            parse_mode="Markdown",
            reply_markup=errand_keyboard()
        )
        return CHOOSING_ERRAND
    elif text == "⚡ Express Delivery":
        return await express_start(update, context)
    elif text == "📅 Schedule Delivery":
        return await schedule_start(update, context)
    elif text == "💰 Price Quote":
        return await pricing(update, context)
    elif text == "🗺️ View Zones":
        return await zones(update, context)
    elif text == "💳 Payment Info":
        return await payment(update, context)
    elif text == "📞 Contact Us":
        return await contact(update, context)
    elif text == "ℹ️ About BikeBlitz":
        return await about(update, context)
    elif text == "🆘 Report an Issue":
        await update.message.reply_text(
            "🆘 *We're here to help.*\n\n"
            "Please describe what's wrong — a late delivery, a rude rider, a payment issue, "
            "anything at all. This goes straight to our team.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
        )
        return AWAITING_SUPPORT_MESSAGE
    else:
        await update.message.reply_text(
            "I didn't understand that. Please use the menu below 👇",
            reply_markup=main_menu()
        )
        return CHOOSING_SERVICE


async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

    user = update.effective_user
    contact = f"@{user.username}" if user.username else f"Telegram ID {user.id}"

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🆘 *Support Request*\n\n"
                f"👤 {user.full_name} ({contact})\n\n"
                f"\"{text}\""
            ),
            parse_mode="Markdown",
        )
    except Exception:
        logger.exception("Failed to forward support message to admin")

    await update.message.reply_text(
        "✅ Got it — we've received your message and will get back to you shortly.\n\n"
        "Thanks for your patience! 🙏",
        reply_markup=main_menu()
    )
    return CHOOSING_SERVICE


def main():
    # Workaround for a known python-telegram-bot issue on some hosts where
    # asyncio.get_event_loop() fails with "no current event loop in thread
    # 'MainThread'" even though nothing else touched asyncio yet.
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        ],
        states={
            CHOOSING_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            CHOOSING_ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_zone)],
            CHOOSING_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weight)],
            CHOOSING_BUSSTOP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_busstop)],
            CHOOSING_LOCATION_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location_details)],
            AWAITING_SUPPORT_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_support_message)],
            AWAITING_ERRAND_ITEMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_errand_items)],
            CHOOSING_ERRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_errand)],
            CONFIRMING_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirm)],
            AWAITING_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_promo_code)],
            SCHEDULING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_schedule_time)],
            AWAITING_PAYMENT_PROOF: [
                MessageHandler(filters.PHOTO, handle_payment_proof),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_proof),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    apply_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("apply", apply_start)],
        states={
            APPLY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_name)],
            APPLY_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_phone)],
            APPLY_ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_zone)],
            APPLY_BIKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_bike)],
            APPLY_AVAILABILITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_availability)],
            APPLY_JUDGMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, apply_judgment)],
        },
        fallbacks=[CommandHandler("apply", apply_start)],
    )

    # Registered before the main conv_handler so an in-progress application
    # takes priority over the customer-ordering flow for the same chat.
    app.add_handler(apply_conv_handler)
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_rider_application_decision, pattern=r"^(riderapprove|riderreject):"))
    app.add_handler(CallbackQueryHandler(handle_admin_decision, pattern=r"^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(handle_rider_claim, pattern=r"^claim:"))
    app.add_handler(CallbackQueryHandler(handle_delivered, pattern=r"^delivered:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_order, pattern=r"^cancelorder:"))
    app.add_handler(CallbackQueryHandler(handle_rating, pattern=r"^rate:"))
    app.add_handler(CommandHandler("zones", zones))
    app.add_handler(CommandHandler("pricing", pricing))
    app.add_handler(CommandHandler("payment", payment))
    app.add_handler(CommandHandler("contact", contact))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("groupid", groupid))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("online", online))
    app.add_handler(CommandHandler("offline", offline))
    app.add_handler(CommandHandler("whosonline", whosonline))
    app.add_handler(CommandHandler("setzone", setzone))
    app.add_handler(CommandHandler("myearnings", myearnings))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("myreferral", myreferral))
    app.add_handler(CommandHandler("referral", referral))
    app.add_handler(CommandHandler("createpromo", createpromo))

    # Global handler (separate group) — catches delivery proof photos from riders
    # regardless of what conversation state the customer-facing flow is in.
    app.add_handler(MessageHandler(filters.PHOTO, handle_delivery_proof_photo), group=1)

    # Weekly recap — Sunday 9 PM WAT (20:00 UTC, since WAT is UTC+1)
    if app.job_queue is not None:
        app.job_queue.run_daily(
            send_weekly_summary,
            time=dt_time(hour=20, minute=0),
            days=(6,),
            name="weekly_summary",
        )
        # Daily cutoff reminder — 7:30 PM WAT (18:30 UTC), 30 min before the 8 PM cutoff
        app.job_queue.run_daily(
            send_cutoff_reminder,
            time=dt_time(hour=18, minute=30),
            name="cutoff_reminder",
        )

    # --- Webhook setup for Render ---
    # Render sets PORT automatically. RENDER_EXTERNAL_URL is your service's public URL,
    # also set automatically by Render for web services.
    port = int(os.environ.get("PORT", "10000"))
    external_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not external_url:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL is not set. This should be set automatically by Render."
        )

    # Use the bot token as the URL path secret so randoms can't hit your webhook.
    url_path = TOKEN
    webhook_url = f"{external_url}/{url_path}"

    print(f"BikeBlitz Bot starting in webhook mode: {webhook_url}")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path,
        webhook_url=webhook_url,
    )


if __name__ == "__main__":
    main()
