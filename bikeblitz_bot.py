import os
import json
import logging
from datetime import datetime
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

# --- Google Sheets transaction logging ---
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

_gsheet = None


def get_sheet():
    """Lazily connect to the Google Sheet. Returns None if not configured or on error."""
    global _gsheet
    if _gsheet is not None:
        return _gsheet
    if not GOOGLE_SHEET_ID or not GOOGLE_SERVICE_ACCOUNT_JSON:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        _gsheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
        return _gsheet
    except Exception:
        logger.exception("Failed to connect to Google Sheets")
        return None


def log_transaction(customer_name, telegram_id, service, zone, location, delivery_type, total):
    """Append one approved transaction as a new row. Silently logs errors, never crashes the bot."""
    try:
        sheet = get_sheet()
        if sheet is None:
            logger.warning("Google Sheets not configured — skipping transaction log")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([
            timestamp, customer_name, str(telegram_id), service, zone,
            location, delivery_type, total
        ])
    except Exception:
        logger.exception("Failed to log transaction to Google Sheets")

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
) = range(9)

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

ZONE_LOCATIONS = {
    "Zone 1 - On Campus": "Anywhere within FUNAAB campus",
    "Zone 2 - Near Off Campus": "Harmony, Accord, Zoo, Agbede, Kofesu",
    "Zone 3 - Mid Off Campus": "Labuta, Isolu-Cele, Isolu-FUNIS, Camp",
    "Zone 4 - Far Off Campus": "Town",
}


# ---------- Keyboards ----------

def main_menu():
    keyboard = [
        [KeyboardButton("📦 Send a Package"), KeyboardButton("🛒 Errand / Food / Market")],
        [KeyboardButton("⚡ Express Delivery"), KeyboardButton("📅 Schedule Delivery")],
        [KeyboardButton("💰 Price Quote"), KeyboardButton("🗺️ View Zones")],
        [KeyboardButton("💳 Payment Info"), KeyboardButton("📞 Contact Us")],
        [KeyboardButton("ℹ️ About BikeBlitz")],
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
        [KeyboardButton("❌ Cancel Order")],
        [KeyboardButton("🏠 Main Menu")],
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


async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(
        f"Chat ID: `{chat.id}`\nChat type: {chat.type}",
        parse_mode="Markdown"
    )




async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome to *BikeBlitz* 🚴\n\n"
        "FUNAAB's fastest campus delivery and errand service.\n\n"
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

    await update.message.reply_text(
        "📝 One last thing — please describe your *exact location* within the zone "
        "(hostel/building name, house number, nearest landmark, etc.) so your rider "
        "can find you door-to-door.\n\n"
        "_Example: Alpha Hostel, Room 14, behind the FUNAAB clinic_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("🏠 Main Menu")]], resize_keyboard=True)
    )
    return CHOOSING_LOCATION_DETAILS


async def handle_location_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 Main Menu":
        return await start(update, context)

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

        context.user_data["total"] = total
        context.user_data["base_price"] = base_price
        context.user_data["distance_add"] = distance_add
        context.user_data["express_add"] = express_add

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
        breakdown += (
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 *Total Delivery Charge: ₦{total:,}*\n\n"
            f"Rider earns: ₦{int(total * 0.7):,} (70%)\n"
            f"BikeBlitz: ₦{int(total * 0.3):,} (30%)\n\n"
            f"Would you like to confirm this order? 👇"
        )
    else:
        errand_fee = context.user_data.get("errand_fee", 100)
        errand_type = context.user_data.get("errand_type")
        base_price = ZONE_PRICES[zone]["Light"]
        distance_add = DISTANCE_MODIFIER if far_from_busstop else 0
        express_add = EXPRESS_SURCHARGE if delivery_type == "Express" else 0
        total = base_price + errand_fee + distance_add + express_add

        context.user_data["total"] = total
        context.user_data["base_price"] = base_price
        context.user_data["distance_add"] = distance_add
        context.user_data["express_add"] = express_add

        breakdown = (
            f"📋 *Order Summary*\n\n"
            f"🛒 Service: {errand_type}\n"
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
        breakdown += (
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 *Total Delivery Charge: ₦{total:,}*\n\n"
            f"_Item cost paid directly to vendor_\n\n"
            f"Would you like to confirm this order? 👇"
        )

    if delivery_type == "Scheduled":
        scheduled_time = context.user_data.get("scheduled_time", "")
        breakdown += f"\n📅 Scheduled for: *{scheduled_time}*"

    await update.message.reply_text(breakdown, parse_mode="Markdown", reply_markup=confirm_keyboard())
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

    if text == "✅ Confirm Order":
        total = context.user_data.get("total", 0)
        delivery_type = context.user_data.get("delivery_type", "Standard")
        scheduled_time = context.user_data.get("scheduled_time", "")

        confirmation = (
            f"✅ *Order Confirmed!*\n\n"
            f"💳 *Total Delivery Charge: ₦{total:,}*\n\n"
            f"Please transfer ₦{total:,} to:\n"
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
    scheduled_time = context.user_data.get("scheduled_time", "")
    location_details = context.user_data.get("location_details", "Not provided")

    summary = (
        f"💰 *New Payment Received*\n\n"
        f"👤 Customer: {user.full_name} (@{user.username or 'no username'})\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"🛠️ Service: {service} {f'- {weight}' if weight else ''}{f'- {errand_type}' if errand_type else ''}\n"
        f"🗺️ Zone: {zone}\n"
        f"📍 Exact location: {location_details}\n"
        f"🚴 Delivery Type: {delivery_type}\n"
    )
    if scheduled_time:
        summary += f"📅 Scheduled: {scheduled_time}\n"
    summary += f"💳 Total: ₦{total:,}"

    # Forward the screenshot + summary to the admin, with Approve/Reject buttons
    photo_file_id = update.message.photo[-1].file_id

    # Stash order info so the approve/reject handler can message the right customer
    # and log the transaction once approved
    pending = context.application.bot_data.setdefault("pending_orders", {})
    pending[str(user.id)] = {
        "customer_name": user.full_name,
        "total": total,
        "delivery_type": delivery_type,
        "scheduled_time": scheduled_time,
        "service": service,
        "zone": zone,
        "location": location_details,
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
        total = order.get("total", 0) if order else 0
        delivery_type = order.get("delivery_type", "Standard") if order else "Standard"
        scheduled_time = order.get("scheduled_time", "") if order else ""
        service = order.get("service", "N/A") if order else "N/A"
        zone = order.get("zone", "N/A") if order else "N/A"
        location = order.get("location", "N/A") if order else "N/A"

        msg = (
            "✅ *Payment Confirmed!*\n\n"
            f"Your delivery charge of ₦{total:,} has been verified.\n\n"
            "Your rider will be dispatched immediately ⚡\n\n"
        )
        if delivery_type == "Scheduled" and scheduled_time:
            msg += f"📅 Your delivery is scheduled for: *{scheduled_time}*\n\n"
        msg += "Thank you for choosing BikeBlitz! 🚴"

        await context.bot.send_message(chat_id=customer_id, text=msg, parse_mode="Markdown")
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n✅ *APPROVED*",
            parse_mode="Markdown",
        )

        log_transaction(
            customer_name=customer_name,
            telegram_id=customer_id,
            service=service,
            zone=zone,
            location=location,
            delivery_type=delivery_type,
            total=total,
        )
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
    else:
        await update.message.reply_text(
            "I didn't understand that. Please use the menu below 👇",
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
            CHOOSING_ERRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_errand)],
            CONFIRMING_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirm)],
            SCHEDULING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_schedule_time)],
            AWAITING_PAYMENT_PROOF: [
                MessageHandler(filters.PHOTO, handle_payment_proof),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_proof),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_admin_decision, pattern=r"^(approve|reject):"))
    app.add_handler(CommandHandler("zones", zones))
    app.add_handler(CommandHandler("pricing", pricing))
    app.add_handler(CommandHandler("payment", payment))
    app.add_handler(CommandHandler("contact", contact))
    app.add_handler(CommandHandler("about", about))
    app.add_handler(CommandHandler("groupid", groupid))

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
