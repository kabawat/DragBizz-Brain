"""User-facing capability help derived from the authorized runtime registry."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.tool import ToolDefinition, ToolRisk, ToolSideEffect

CAPABILITY_CATALOG_VERSION = "1.0.0"

# Stable product-facing labels; membership always comes from the live,
# permission-filtered tool definitions passed by the caller.
_CAPABILITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Sales and billing",
        (
            "today_sale",
            "list_invoices",
            "invoice_summary",
            "create_invoice_draft",
            "release_invoice",
        ),
    ),
    (
        "Products and stock",
        (
            "search_product",
            "product_summary",
            "stock_summary",
            "stock_items",
            "add_stock",
        ),
    ),
    (
        "Customers and khata",
        (
            "search_customer",
            "customer_dossier",
            "customer_summary",
            "list_customer_accounts",
            "get_customer_ledger",
            "create_customer",
            "update_customer",
            "record_customer_payment",
            "send_payment_reminder",
        ),
    ),
    (
        "Expenses and cashbook",
        (
            "list_expenses",
            "expense_summary",
            "create_expense",
            "update_expense",
            "cashbook_summary",
        ),
    ),
    (
        "Suppliers and purchase orders",
        (
            "search_supplier",
            "supplier_summary",
            "list_supplier_bills",
            "bill_summary",
            "list_purchase_orders",
            "create_purchase_order",
        ),
    ),
    (
        "Other store operations",
        ("list_sales_orders", "gst_summary", "list_staff", "list_stores"),
    ),
)


def build_capability_help(
    definitions: Iterable[ToolDefinition], *, language: str = "en"
) -> str:
    """Describe only enabled and authorized operations, with truthful write boundaries."""
    by_name = {item.name: item for item in definitions}
    sections: list[str] = []
    for label, names in _CAPABILITIES:
        present = [by_name[name] for name in names if name in by_name]
        if not present:
            continue
        readable = any(item.risk == ToolRisk.READ for item in present)
        writable = [item for item in present if item.risk != ToolRisk.READ]
        phrases: list[str] = []
        if readable:
            phrases.append("check live records and answer questions")
        if any(item.side_effect == ToolSideEffect.DRAFT for item in writable):
            phrases.append("prepare or update drafts")
        if any(item.risk == ToolRisk.WRITE for item in writable):
            phrases.append("make supported changes")
        if any(item.risk == ToolRisk.SENSITIVE for item in writable):
            phrases.append("prepare sensitive actions for your confirmation")
        sections.append(f"• **{label}**: {', '.join(phrases)}")

    if not sections:
        if language.lower().startswith("en"):
            return (
                "I’m DragAI, but I can’t verify which chat operations are "
                "enabled for this account right now. Please check the relevant "
                "dashboard page or ask your Store Admin to review access."
            )
        return (
            "Main DragAI hoon, lekin abhi is account ke liye chat operations "
            "verify nahi kar pa raha. Dashboard me feature check karein ya Store "
            "Admin se access confirm karein."
        )

    boundary = "Supplier bill payment is managed from the dashboard; I cannot submit that payment in chat."
    if language.lower().startswith("hi"):
        intro = "Main DragAI hoon. Is account par jo operations available hain, unmein main:"
        close = "Kuch changes seedhe ho sakte hain; sensitive actions pehle preview hote hain aur confirmation ke baad hi commit hote hain."
        return "\n".join((intro, *sections, boundary, close))
    intro = "I’m DragAI. With the operations available to this account, I can:"
    close = "Some supported changes run directly; sensitive actions are previewed and committed only after your confirmation."
    return "\n".join((intro, *sections, boundary, close))
