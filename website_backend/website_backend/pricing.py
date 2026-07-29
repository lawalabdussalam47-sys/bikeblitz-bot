"""
Pricing constants — mirrored from bikeblitz_bot.py. If you change prices in the bot,
update this file too, or orders quoted here won't match what riders/admin see.
"""

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


def calculate_total(service, zone, weight=None, errand_type=None, express=False, far_busstop=False):
    """Returns (total, breakdown_dict) or (None, error_message) if inputs are invalid."""
    if zone not in ZONE_PRICES:
        return None, "Invalid zone"

    distance_add = DISTANCE_MODIFIER if far_busstop else 0
    express_add = EXPRESS_SURCHARGE if express else 0

    if service == "B2B":
        if weight not in ZONE_PRICES[zone]:
            return None, "Invalid weight"
        base = ZONE_PRICES[zone][weight]
        total = base + distance_add + express_add
        return total, {"base": base, "distanceAdd": distance_add, "expressAdd": express_add, "total": total}

    if service == "B2C":
        if errand_type not in ERRAND_FEES:
            return None, "Invalid errand type"
        base = ZONE_PRICES[zone]["Light"]
        fee = ERRAND_FEES[errand_type]
        total = base + fee + distance_add + express_add
        return total, {"base": base, "fee": fee, "distanceAdd": distance_add, "expressAdd": express_add, "total": total}

    return None, "Invalid service"
