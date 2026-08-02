import os
import logging
import uuid

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
    far_busstop = bool(body.get("farBusstop"))
    location = (body.get("location") or "").strip()
    customer_name = (body.get("customerName") or "").strip()
    phone = (body.get("phone") or "").strip()
    email = (body.get("email") or "").strip()
    delivery_type = "Express" if express else "Standard"

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

    sheets.update_web_order(reference, Status="Paid")
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
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10001"))
    app.run(host="0.0.0.0", port=port)
