import os
import logging
import uuid
import random

from flask import Flask, request, jsonify
from flask_cors import CORS

from pricing import calculate_total, ZONE_PRICES, ERRAND_FEES
import sheets
import paystack
import telegram_notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # allow the frontend (hosted separately) to call this API

SITE_URL = os.environ.get("SITE_URL", "http://localhost:5173")


def generate_pickup_code():
    """Generates a random 4-digit pickup verification code as a string, e.g. '4821'.
    Kept identical in format to the one the Telegram bot generates for bot-native
    orders, though the two are independent — each backend has its own WebOrders row."""
    return f"{random.randint(0, 9999):04d}"


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


@app.route("/api/riders/status")
def riders_status():
    count = sheets.get_online_rider_count()
    return jsonify({"onlineCount": count})


@app.route("/api/quote", methods=["POST"])
def quote():
    body = request.get_json(force=True) or {}
    total, breakdown = calculate_total(
        service=body.get("service"),
        zone=body.get("zone"),
        weight=body.get("weight"),
        errand_type=body.get("errandType"),
        express=bool(body.get("express")),
        far_busstop=bool(body.get("farBusstop")),
    )
    if total is None:
        return jsonify({"error": breakdown}), 400
    return jsonify(breakdown)


@app.route("/api/orders", methods=["POST"])
def create_order():
    body = request.get_json(force=True) or {}

    service = body.get("service")
    zone = body.get("zone")
    weight = body.get("weight")
    errand_type = body.get("errandType")
    errand_items = body.get("errandItems", "")
    express = bool(body.get("express"))
    scheduled_time = (body.get("scheduledTime") or "").strip()
    far_busstop = bool(body.get("farBusstop"))
    location = (body.get("location") or "").strip()
    customer_name = (body.get("customerName") or "").strip()
    phone = (body.get("phone") or "").strip()
    email = (body.get("email") or "").strip()
    delivery_type = f"Scheduled: {scheduled_time}" if scheduled_time else ("Express" if express else "Standard")

    if not customer_name or not phone or not email or not location:
        return jsonify({"error": "Name, phone, email, and location are all required."}), 400

    total, breakdown = calculate_total(service, zone, weight, errand_type, express, far_busstop)
    if total is None:
        return jsonify({"error": breakdown}), 400

    reference = f"bb_{uuid.uuid4().hex[:16]}"

    created = sheets.create_web_order(
        reference=reference,
        customer_name=customer_name,
        phone=phone,
        service=service,
        zone=zone,
        location=location,
        errand_items=errand_items if service == "B2C" else "",
        delivery_type=delivery_type,
        total=total,
    )
    if not created:
        return jsonify({"error": "Couldn't save your order right now — try again shortly."}), 500

    authorization_url, error = paystack.initialize_transaction(
        email=email,
        amount_naira=total,
        reference=reference,
        callback_url=f"{SITE_URL}/?reference={reference}",
        metadata={"customer_name": customer_name, "phone": phone, "zone": zone, "service": service},
    )
    if error:
        return jsonify({"error": error}), 502

    return jsonify({"reference": reference, "authorizationUrl": authorization_url, "total": total})


@app.route("/api/paystack/webhook", methods=["POST"])
def paystack_webhook():
    signature = request.headers.get("x-paystack-signature", "")
    if not paystack.verify_webhook_signature(request.data, signature):
        logger.warning("Rejected webhook with invalid signature")
        return "", 401

    event = request.get_json(force=True) or {}
    if event.get("event") != "charge.success":
        return "", 200

    reference = event.get("data", {}).get("reference")
    if not reference:
        return "", 200

    verified, amount_kobo, error = paystack.verify_transaction(reference)
    if error or not verified:
        logger.warning(f"Webhook claimed success but verification failed for {reference}: {error}")
        return "", 200

    order = sheets.get_web_order(reference)
    if order is None:
        logger.warning(f"Webhook for unknown order reference {reference}")
        return "", 200

    if order.get("Status") not in ("Pending Payment", ""):
        return "", 200

    total = int(order.get("Total", 0) or 0)
    if amount_kobo != total * 100:
        logger.warning(f"Amount mismatch for {reference}: expected {total * 100}, got {amount_kobo}")
        telegram_notify.notify_admin(
            f"⚠️ Payment amount mismatch on web order {reference} — please check manually."
        )
        return "", 200

    # Generate the pickup verification code now, at the moment payment is confirmed —
    # only if this order doesn't already have one (webhooks can be delivered more than
    # once, and we don't want a retry to hand the customer a second, different code).
    # This code is shown to the customer on the tracking page; the RIDER is the one who
    # enters it (via /verify in Telegram, after asking the customer for it in person) —
    # that's the actual security check. The website's own /deliver endpoint below does
    # NOT require this code, since a customer confirming their own delivery by re-typing
    # a code already shown to them isn't meaningful verification.
    pickup_code = order.get("Pickup Code") or generate_pickup_code()

    sheets.update_web_order(reference, **{"Status": "Paid", "Pickup Code": pickup_code})
    sheets.log_transaction(
        customer_name=order.get("Customer Name"),
        telegram_id=None,
        service=order.get("Service"),
        zone=order.get("Zone"),
        location=order.get("Location"),
        delivery_type=order.get("Delivery Type"),
        total=total,
    )

    message_id = telegram_notify.broadcast_web_order_to_riders(
        reference=reference,
        service=order.get("Service"),
        zone=order.get("Zone"),
        location=order.get("Location"),
        errand_items=order.get("Errand Items", ""),
        delivery_type=order.get("Delivery Type"),
        total=total,
    )
    if message_id:
        sheets.update_web_order(reference, **{"Broadcast Message ID": message_id})

    return "", 200


@app.route("/api/orders/<reference>", methods=["GET"])
def order_status(reference):
    order = sheets.get_web_order(reference)
    if order is None:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({
        "reference": reference,
        "status": order.get("Status"),
        "riderName": order.get("Rider Name") or None,
        "zone": order.get("Zone"),
        "total": order.get("Total"),
        "pickupCode": order.get("Pickup Code") or None,
    })


@app.route("/api/orders/<reference>/deliver", methods=["POST"])
def confirm_delivery(reference):
    """Customer-facing self-confirmation: the customer marks their own order delivered
    and attaches a photo as proof. This does NOT check the pickup code — that
    verification happens separately and more meaningfully on the rider's side, via the
    /verify command in Telegram, where the rider has to actually ask the customer for
    the code in person before the bot lets them complete the delivery."""
    order = sheets.get_web_order(reference)
    if order is None:
        return jsonify({"error": "Order not found"}), 404

    if order.get("Status") == "Delivered":
        return jsonify({"error": "This order has already been marked as delivered."}), 400

    photo = request.files.get("photo")
    if not photo or not photo.filename:
        return jsonify({"error": "A delivery photo is required."}), 400

    photo_bytes = photo.read()
    if len(photo_bytes) == 0:
        return jsonify({"error": "The uploaded photo appears to be empty."}), 400

    sheets.update_web_order(reference, Status="Delivered")

    telegram_notify.send_delivery_proof(
        reference=reference,
        photo_bytes=photo_bytes,
        filename=photo.filename,
        zone=order.get("Zone"),
        location=order.get("Location"),
    )

    return jsonify({"reference": reference, "status": "Delivered"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10001"))
    app.run(host="0.0.0.0", port=port)
