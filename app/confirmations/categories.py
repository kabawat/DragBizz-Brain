"""Expense category definitions and normalization for store expenses."""

from __future__ import annotations

EXPENSE_CATEGORY_MAP: dict[str, str] = {
    "daily-expenses": "Tea & Snacks (Chai)",
    "rent": "Rent (Kiraya)",
    "transport": "Transport (Dhulai)",
    "shop-supplies": "Shop Supplies",
    "staff-wages": "Staff Wages",
    "utilities": "Electricity & Water",
    "office-supplies": "Office Supplies",
    "travel": "Travel & Transport",
    "marketing": "Marketing & Advertising",
    "promotions": "Promotions & Discounts",
    "legal": "Legal & Professional",
    "insurance": "Insurance",
    "maintenance": "Maintenance & Repairs",
    "cleaning": "Cleaning & Housekeeping",
    "communication": "Communication",
    "training": "Training & Development",
    "miscellaneous": "Miscellaneous",
}

_CHAI_KEYWORDS = (
    "chai",
    "tea",
    "snack",
    "nashta",
    "refreshment",
    "samosa",
    "coffee",
    "biscuit",
    "meal",
    "lunch",
    "dinner",
    "food",
)
_RENT_KEYWORDS = ("rent", "kiraya", "godown rent", "shop rent")
_TRANSPORT_KEYWORDS = (
    "transport",
    "dhulai",
    "delivery",
    "fuel",
    "petrol",
    "diesel",
    "auto",
    "tempo",
    "carriage",
    "loading",
)
_WAGE_KEYWORDS = (
    "wage",
    "salary",
    "pagar",
    "helper",
    "bonus",
    "mazdoor",
    "mazdoori",
    "staff",
)
_UTILITY_KEYWORDS = (
    "elect",
    "bijli",
    "water",
    "pani",
    "gas",
    "utility",
    "utilities",
    "light bill",
)
_SHOP_SUPPLIES_KEYWORDS = ("bag", "packaging", "polythene", "packing", "shop-supplies")
_OFFICE_SUPPLIES_KEYWORDS = (
    "stationery",
    "paper",
    "register",
    "pen",
    "office-supplies",
)


def normalize_expense_category(
    raw_category: str | None,
    title: str | None = None,
) -> tuple[str, str]:
    """Map user/LLM raw category or title to (category_value, category_label).

    Ensures expenses map to valid DragBizz store categories (e.g. 'daily-expenses'
    for Chai/Tea/Snacks rather than defaulting to Rent).
    """
    cat = (raw_category or "").strip().lower()
    tit = (title or "").strip().lower()
    combined = f"{cat} {tit}".strip()

    # Exact value match first
    if cat in EXPENSE_CATEGORY_MAP:
        return cat, EXPENSE_CATEGORY_MAP[cat]

    # Keyword rules
    if any(k in combined for k in _CHAI_KEYWORDS):
        return "daily-expenses", EXPENSE_CATEGORY_MAP["daily-expenses"]

    if any(k in combined for k in _RENT_KEYWORDS):
        return "rent", EXPENSE_CATEGORY_MAP["rent"]

    if any(k in combined for k in _TRANSPORT_KEYWORDS):
        return "transport", EXPENSE_CATEGORY_MAP["transport"]

    if any(k in combined for k in _WAGE_KEYWORDS):
        return "staff-wages", EXPENSE_CATEGORY_MAP["staff-wages"]

    if any(k in combined for k in _UTILITY_KEYWORDS):
        return "utilities", EXPENSE_CATEGORY_MAP["utilities"]

    if any(k in combined for k in _SHOP_SUPPLIES_KEYWORDS):
        return "shop-supplies", EXPENSE_CATEGORY_MAP["shop-supplies"]

    if any(k in combined for k in _OFFICE_SUPPLIES_KEYWORDS):
        return "office-supplies", EXPENSE_CATEGORY_MAP["office-supplies"]

    if any(k in combined for k in ("repair", "maintenance", "servicing")):
        return "maintenance", EXPENSE_CATEGORY_MAP["maintenance"]

    if any(k in combined for k in ("clean", "safai", "housekeeping")):
        return "cleaning", EXPENSE_CATEGORY_MAP["cleaning"]

    if any(
        k in combined
        for k in ("recharge", "phone", "mobile", "wifi", "internet", "communication")
    ):
        return "communication", EXPENSE_CATEGORY_MAP["communication"]

    if any(k in combined for k in ("ad", "marketing", "promotion", "banner", "flex")):
        return "marketing", EXPENSE_CATEGORY_MAP["marketing"]

    if any(k in combined for k in ("legal", "lawyer", "advocate", "ca", "audit")):
        return "legal", EXPENSE_CATEGORY_MAP["legal"]

    if any(k in combined for k in ("insurance", "bima")):
        return "insurance", EXPENSE_CATEGORY_MAP["insurance"]

    if any(k in combined for k in ("travel", "hotel", "ticket", "train", "flight")):
        return "travel", EXPENSE_CATEGORY_MAP["travel"]

    # Fallback to miscellaneous (never rent)
    return "miscellaneous", EXPENSE_CATEGORY_MAP["miscellaneous"]
