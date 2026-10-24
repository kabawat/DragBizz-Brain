from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.orchestrator.tool_discovery import (
    GLOBAL_TOOL_RETRIEVER,
    TOOL_METADATA_CATALOG,
    ActionType,
)
from app.schemas.tool import ToolDomain

_PRIOR_EXPOSURE_TURNS = 4

RoutingLabel = Literal["tools", "docs", "both", "neither", "unknown"]

# Default reads when no write exposure matches.
_READ_TOOLS = frozenset(
    {
        "search_product",
        "today_sale",
        "stock_summary",
        "product_summary",
        "search_customer",
        "customer_dossier",
        "top_customers",
        "payment_history",
        "list_stores",
        "customer_summary",
        "get_customer_ledger",
        "list_customer_accounts",
        "get_customer_payment",
        "list_payment_reminders",
        "invoice_summary",
        "stock_items",
        "list_invoices",
        "expense_summary",
        "list_expenses",
        "cashbook_summary",
        "search_supplier",
        "supplier_summary",
        "list_purchase_orders",
        "list_supplier_bills",
        "bill_summary",
        "gst_summary",
        "list_sales_orders",
        "list_staff",
        "customer_detailed_analytics",
        "invoice_detailed_analytics",
        "sales_pareto",
        "payment_mix",
        "inventory_velocity",
        "store_brief",
    }
)

_CORE_UNKNOWN_TOOLS = frozenset(
    {
        "today_sale",
        "stock_summary",
        "search_product",
        "search_customer",
    }
)

DOMAIN_READ_BUNDLES: dict[ToolDomain, frozenset[str]] = {
    ToolDomain.INVENTORY: frozenset(
        {
            "search_product",
            "stock_summary",
            "product_summary",
            "stock_items",
            "inventory_velocity",
            "search_supplier",
        }
    ),
    ToolDomain.PROCUREMENT: frozenset(
        {
            "list_purchase_orders",
            "list_supplier_bills",
            "search_supplier",
            "supplier_summary",
            "bill_summary",
            "search_product",
            "stock_summary",
        }
    ),
    ToolDomain.SALES: frozenset(
        {
            "today_sale",
            "invoice_summary",
            "list_invoices",
            "search_product",
            "search_customer",
            "customer_summary",
            "list_sales_orders",
            "invoice_detailed_analytics",
            "sales_pareto",
        }
    ),
    ToolDomain.KHATA: frozenset(
        {
            "search_customer",
            "customer_dossier",
            "customer_summary",
            "get_customer_ledger",
            "list_customer_accounts",
            "get_customer_payment",
            "payment_history",
            "list_payment_reminders",
            "today_sale",
        }
    ),
    ToolDomain.FINANCE: frozenset(
        {
            "expense_summary",
            "list_expenses",
            "cashbook_summary",
            "gst_summary",
            "today_sale",
        }
    ),
    ToolDomain.GENERAL: frozenset(
        {
            "store_brief",
            "today_sale",
            "stock_summary",
            "customer_summary",
            "invoice_summary",
            "search_product",
            "search_customer",
            "list_staff",
            "list_stores",
        }
    ),
}

DOMAIN_WRITE_BUNDLES: dict[ToolDomain, frozenset[str]] = {
    ToolDomain.INVENTORY: frozenset({"add_stock"}),
    ToolDomain.PROCUREMENT: frozenset({"create_purchase_order"}),
    ToolDomain.SALES: frozenset(
        {
            "create_invoice_draft",
            "update_invoice_draft",
            "release_invoice",
        }
    ),
    ToolDomain.KHATA: frozenset(
        {
            "ledger_credit",
            "ledger_debit",
            "record_customer_payment",
            "update_customer_payment",
            "create_customer",
            "update_customer",
            "set_opening_balance",
            "merge_customers",
            "create_collect_link",
            "send_payment_reminder",
        }
    ),
    ToolDomain.FINANCE: frozenset(
        {
            "create_expense",
            "update_expense",
        }
    ),
    ToolDomain.GENERAL: frozenset(),
}

DOMAIN_BUNDLES: dict[ToolDomain, frozenset[str]] = {
    d: DOMAIN_READ_BUNDLES[d] | DOMAIN_WRITE_BUNDLES[d]
    for d in DOMAIN_READ_BUNDLES
}

SAFE_BROAD_STORE_FALLBACK: frozenset[str] = frozenset(
    {
        "today_sale",
        "stock_summary",
        "search_product",
        "search_customer",
        "invoice_summary",
        "expense_summary",
        "search_supplier",
        "list_purchase_orders",
        "get_customer_ledger",
        "store_brief",
    }
)

_FAMILY_READS: dict[str, frozenset[str]] = {
    "sale": frozenset({"today_sale", "invoice_summary", "list_invoices"}),
    "stock": frozenset({"stock_summary", "search_product"}),
    "stock_items": frozenset({"stock_items", "stock_summary", "search_product"}),
    "product": frozenset({"search_product"}),
    "product_stats": frozenset({"product_summary"}),
    "payment": frozenset({"payment_history", "search_customer"}),
    "payment_detail": frozenset({"get_customer_payment", "payment_history"}),
    "payment_reminders": frozenset({"list_payment_reminders", "search_customer"}),
    # Lookup/create flows need search only; payment history is payment-family.
    "customer": frozenset({"search_customer"}),
    "customer_ledger": frozenset(
        {"get_customer_ledger", "list_customer_accounts", "search_customer"}
    ),
    "customer_accounts": frozenset({"list_customer_accounts", "search_customer"}),
    "customer_stats": frozenset({"customer_summary"}),
    "invoice": frozenset({"search_customer", "search_product"}),
    "invoices": frozenset({"list_invoices", "invoice_summary", "today_sale"}),
    "invoice_stats": frozenset({"invoice_summary", "today_sale"}),
    "expense": frozenset({"expense_summary", "list_expenses"}),
    "cashbook": frozenset({"cashbook_summary", "today_sale"}),
    "supplier": frozenset(
        {"search_supplier", "supplier_summary", "bill_summary", "list_supplier_bills"}
    ),
    "purchase_order": frozenset(
        {"list_purchase_orders", "search_supplier", "search_product"}
    ),
    "bill": frozenset(
        {"bill_summary", "list_supplier_bills", "supplier_summary", "search_supplier"}
    ),
    "gst": frozenset({"gst_summary", "invoice_summary"}),
    "sales_order": frozenset({"list_sales_orders", "search_customer"}),
    "staff": frozenset({"list_staff"}),
    "detailed_analytics": frozenset(
        {
            "customer_detailed_analytics",
            "invoice_detailed_analytics",
            "customer_summary",
            "invoice_summary",
            "stock_summary",
            "search_product",
        }
    ),
    "business_advisor": frozenset(
        {
            "invoice_summary",
            "today_sale",
            "stock_summary",
            "search_product",
            "customer_summary",
            "top_customers",
            "expense_summary",
        }
    ),
    "store": frozenset({"list_stores"}),
    "sales_pareto": frozenset({"sales_pareto", "today_sale", "invoice_summary"}),
    "payment_mix": frozenset({"payment_mix", "today_sale", "cashbook_summary"}),
    "inventory_velocity": frozenset(
        {"inventory_velocity", "stock_items", "stock_summary"}
    ),
    "store_brief": frozenset(
        {
            "store_brief",
            "today_sale",
            "stock_summary",
            "expense_summary",
            "customer_summary",
        }
    ),
}

# Write tools from action phrases (not short sensitive tokens alone).
_EXPOSURE: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (
        (
            "naya customer",
            "customer banao",
            "customer bana",
            "create customer",
            "create a customer",
            "create a new customer",
            "create new customer",
            "add customer",
            "add a customer",
            "add a new customer",
            "add new customer",
            "customer create",
            "customer add",
        ),
        frozenset({"create_customer"}),
    ),
    (
        (
            "update customer",
            "customer update",
            "edit customer",
            "customer edit",
            "update email",
            "email update",
            "email badlo",
            "email change",
            "email add",
            "add email",
            "email bhi",
            "email daal",
            "email dalo",
            "email daalo",
            "update phone",
            "phone update",
            "number update",
            "phone badlo",
            "number badlo",
            "update details",
            "details update",
            "update address",
            "address update",
            "address badlo",
            "address add",
            "add address",
            "update gst",
            "gst update",
            "gst add",
            "add gst",
            "gstin add",
            "add gstin",
            "company name",
            "update note",
            "note add",
            "add note",
        ),
        frozenset({"update_customer"}),
    ),
    (
        (
            "merge customer",
            "merge customers",
            "customer merge",
            "duplicate merge",
            "merge duplicate",
            "customers merge",
            "merge karo",
            "merge kar do",
        ),
        frozenset({"merge_customers", "search_customer"}),
    ),
    (
        (
            "opening balance",
            "set opening balance",
            "opening balance set",
            "khata opening",
            "opening khata",
            "shuruati balance",
            "opening due",
        ),
        frozenset({"set_opening_balance", "search_customer"}),
    ),
    (
        (
            "formal payment",
            "structured payment",
            "invoice payment",
            "payment entry",
            "record payment formal",
            "upi payment record",
            "cash payment record",
            "bank payment record",
        ),
        frozenset({"record_customer_payment", "search_customer"}),
    ),
    (
        (
            "update payment note",
            "payment note update",
            "payment notes",
            "edit payment",
        ),
        frozenset({"update_customer_payment"}),
    ),
    (
        (
            "collect link",
            "payment link",
            "payment collect",
            "collect payment link",
            "create collect link",
            "payment link banao",
            "collect link banao",
        ),
        frozenset({"create_collect_link", "search_customer"}),
    ),
    (
        (
            "payment reminder",
            "send reminder",
            "reminder bhejo",
            "reminder send",
            "due reminder",
            "payment yaad dilao",
            "khata reminder",
        ),
        frozenset({"send_payment_reminder", "search_customer"}),
    ),
    (
        (
            "ledger credit",
            "jama karo",
            "jama kar diya",
            "jama kar",
            "jama diya",
            "jama de diya",
            "jama daal",
            "jama dalo",
            "jama add",
            "payment record",
            "payment add",
            "payment mila",
            "payment liya",
            "payment le liya",
            "paid karo",
            "khata jama",
            "credit add",
        ),
        frozenset({"ledger_credit"}),
    ),
    (
        (
            "ledger debit",
            "udhaar add",
            "udhaar dalo",
            "udhar add",
            "udhar dalo",
            "udhaar le",
            "udhar le",
            "udhaar laga",
            "udhar laga",
            "mere se udhaar",
            "mere se udhar",
            "khate me add",
            "khata me add",
            "khate mein add",
            "khata mein add",
            "khate me daal",
            "khata me daal",
            "due add",
            "debit add",
        ),
        frozenset({"ledger_debit"}),
    ),
    (
        (
            "bill banao",
            "bill bana",
            "invoice banao",
            "invoice bana",
            "create invoice",
            "create bill",
            "make a bill",
            "make bill",
            "make an invoice",
            "make invoice",
            "draft invoice",
            "invoice draft",
            "bill for",
            "ke liye bill",
            "ke liye invoice",
            "બિલ બનાવો",
            "ઇનવોઇસ બનાવો",
            "નવું બિલ",
            "ચલણ બનાવો",
            "બિલ બનાવી આપો",
        ),
        frozenset(
            {
                "create_customer",
                "create_invoice_draft",
                "update_invoice_draft",
            }
        ),
    ),
    (
        ("release invoice", "release the draft", "release draft"),
        frozenset({"release_invoice"}),
    ),
    (
        (
            "stock add",
            "add stock",
            "stock badhao",
            "stock badha",
            "stock daalo",
            "stock dalo",
            "stock daal",
            "stock me add",
            "stock mein add",
            "stock me daal",
            "stock mein daal",
            "inventory add",
            "add inventory",
            "unit add",
            "units add",
            "units daalo",
            "units dalo",
            "stock in",
            "stock intake",
            "maal aaya",
            "maal add",
            "stock update",
        ),
        frozenset({"add_stock", "search_product"}),
    ),
    (
        (
            "add kharcha",
            "kharcha add",
            "add karo kharcha",
            "add karo kharche",
            "kharche me add",
            "kharcha me add",
            "add expense",
            "expense add",
            "kharcha record",
            "record expense",
            "kharcha dalo",
            "kharcha daalo",
            "kharcha likho",
            "kharcha banao",
            "rent diya",
            "kiraya diya",
            "bill bhara",
            "bill bhra",
            "light bill",
            "bijli bill",
            "electricity bill",
            "kharcha hua",
            "ખર્ચ ઉમેરો",
            "ખર્ચ નોંધો",
            "ખર્ચ એડ",
            "ખર્ચ લખો",
            "ખર્ચો ઉમેરો",
            "ખર્ચો લખો",
            "દુકાનનો ખર્ચ ઉમેરો",
            "દુકાન ખર્ચ ઉમેરો",
            "ભાડું આપ્યું",
            "ભાડું ભર્યું",
            "બિલ ભર્યું",
        ),
        frozenset({"create_expense"}),
    ),
    (
        (
            "update expense",
            "expense update",
            "kharcha update",
            "overdue mark",
            "mark overdue",
            "status update",
            "status badal",
            "status badlo",
            "payment overdue",
        ),
        frozenset({"update_expense"}),
    ),
    (
        (
            "create purchase order",
            "draft purchase order",
            "new purchase order",
            "make purchase order",
            "purchase order create",
            "purchase order draft",
            "create po",
            "draft po",
            "new po",
            "po create",
            "po create krna",
            "po create karna",
            "po banana",
            "po bana",
            "po draft",
            "po banao",
            "purchase order banao",
            "purchase order bana",
            "order from supplier",
            "supplier order",
            "supplier se order",
            "maal order",
            "stock order",
            "સામાન ઓર્ડર",
            "પરચેસ ઓર્ડર",
        ),
        frozenset({"create_purchase_order", "search_supplier", "search_product"}),
    ),
)

_FAMILY_CUES: dict[str, tuple[str, ...]] = {
    "sale": (
        "aaj ki sale",
        "aaj ka sale",
        "aaj ke sales",
        "today's sale",
        "todays sale",
        "today sale",
        "today sales",
        "updated sales",
        "updated sale",
        "sales bata",
        "sale bata",
        "sale batao",
        "sales batao",
        "sale kitni",
        "sale kitna",
        "kitne bill",
        "bill bane",
        "bill banaya",
        "naya bill",
        "ek aur bill",
        "bills today",
        "today's bills",
        "total sell",
        "total sale",
        "total sales",
        "sell kitni",
        "sell kitna",
        "breakdown",
        "breakdown dena",
        "dhandha",
        "aaj ka dhandha",
        "kitna dhandha",
        "dhandha kitna",
        "dhandha hua",
        "kamai",
        "aaj ki kamai",
        "kitni kamai",
        "aavak",
        "bikri",
        "vechan",
        "aaj nu vechan",
        "વેચાણ",
        "આજનું વેચાણ",
        "ધંધો",
        "આજનો ધંધો",
        "કમાણી",
        "આવક",
        "કેટલું વેચાણ",
        "કેટલો ધંધો",
    ),
    "stock": (
        "stock me",
        "stock mein",
        "out of stock",
        "stock kitna",
        "stock kitne",
        "stock bacha",
        "stock summary",
        "low stock",
        "maal",
        "kitna maal",
        "maal kitna",
        "maal bacha",
        "stock check",
        "stock tapaso",
        "jaththo",
        "માલ",
        "જથ્થો",
        "સ્ટોક",
        "સ્ટોક તપાસો",
        "માલ સ્ટોક",
        "કેટલો માલ",
        "કેટલો સ્ટોક",
        "માલ કેટલો",
    ),
    "product": (
        "current price",
        "price kya",
        "price batao",
        "product search",
        "sku",
    ),
    "product_stats": (
        "total product",
        "total products",
        "kitne product",
        "kitane product",
        "kitna product",
        "kitne products",
        "kitane products",
        "how many product",
        "how many products",
        "product listed",
        "products listed",
        "listed product",
        "listed products",
        "product count",
        "products count",
        "product total",
        "products total",
        "catalog me",
        "catalogue me",
        "kitne sku",
        "kitane sku",
        "total sku",
        "total skus",
    ),
    "payment": (
        "payments",
        "payment history",
        "payment dikhao",
        "recent payment",
        "recent payments",
        "payment aaye",
        "payments aaye",
        "payment diya",
        "kitna payment",
        "payment mila",
        "payment received",
        "customer payment",
        "customer payments",
        "payment list",
        "payments list",
        "ચુકવણી",
        "પૈસા",
        "ચુકવ્યા",
        "પૈસા મળ્યા",
        "ચુકવણી ઇતિહાસ",
        "ચુકવણી કરી",
        "પૈસા આપ્યા",
        "કેટલી ચુકવણી",
        "કેટલા પૈસા આવ્યા",
        "ચુકવણી લિસ્ટ",
    ),
    "payment_detail": (
        "payment detail",
        "payment details",
        "ek payment",
        "payment id",
        "get payment",
    ),
    "payment_reminders": (
        "payment reminders",
        "list reminders",
        "reminder list",
        "reminders dikhao",
        "reminder history",
    ),
    "customer": (
        "customer",
        "khata",
        "khate",
        "udhaar",
        "udhar",
        "account",
        "hisab",
        "dues",
        "gstin",
        "baaki",
        "baqi",
        "ka number",
        "ki number",
        "mobile number",
        "phone number",
        "opening balance",
        "merge customer",
        "merge customers",
        "naya customer",
        "customer banao",
        "customer bana",
        "create customer",
        "create a customer",
        "create a new customer",
        "create new customer",
        "add customer",
        "add a customer",
        "add a new customer",
        "add new customer",
        "customer create",
        "customer add",
        "update customer",
        "customer update",
        "edit customer",
        "customer edit",
        "update email",
        "email update",
        "email badlo",
        "email change",
        "email add",
        "add email",
        "email bhi",
        "email daal",
        "email dalo",
        "email daalo",
        "update phone",
        "phone update",
        "number update",
        "phone badlo",
        "number badlo",
        "update details",
        "details update",
        "update address",
        "address update",
        "update gst",
        "gst update",
        "gst add",
        "add gst",
        "ledger credit",
        "ledger debit",
        "udhaar add",
        "udhaar dalo",
        "udhar add",
        "udhar dalo",
        "udhaar le",
        "udhar le",
        "mere se udhaar",
        "mere se udhar",
        "khate me add",
        "khata me add",
        "jama karo",
        "jama kar diya",
        "jama kar",
        "jama diya",
        "jama daal",
        "payment record",
        "payment add",
        "payment mila",
        "khata jama",
    ),
    "customer_ledger": (
        "ledger",
        "customer ledger",
        "khata ledger",
        "credit ledger",
        "account ledger",
        "customer's ledger",
        "ledger dikhao",
        "ledger lines",
        "ledger history",
        "khata history",
        "transaction history",
        "khata",
        "khate",
        "udhar",
        "udhari",
        "baaki",
        "jama",
        "baaki hisaab",
        "khata batao",
        "khata dikhao",
        "ખાતું",
        "ગ્રાહક",
        "ગ્રાહકો",
        "ઉધાર",
        "ઉધારી",
        "બાકી",
        "જમા",
        "ગ્રાહક ખાતું",
        "ખાતું બતાવો",
        "બાકી લિસ્ટ",
        "ચોપડો",
    ),
    "customer_accounts": (
        "due list",
        "dues list",
        "accounts due",
        "due customers",
        "jin ke due",
        "due wale",
        "customers with due",
        "udhari",
        "udhaar list",
        "baaki list",
        "customer dues",
        "customer due",
        "credit ledger",
        "customer dues and credit ledger",
        "dues and credit ledger",
        "pending dues",
        "all list",
        "customer list",
        "dues",
        "udhaar",
        "show customer dues",
        "show dues",
        "all dues",
        "list all",
        "customer accounts",
    ),
    "invoice": (
        "bill banao",
        "bill bana",
        "invoice banao",
        "invoice bana",
        "create invoice",
        "create bill",
        "make a bill",
        "make bill",
        "make an invoice",
        "make invoice",
        "draft invoice",
        "invoice draft",
        "release invoice",
        "release the draft",
        "release draft",
        "bill for",
        "ke liye bill",
        "ke liye invoice",
        "બિલ",
        "ચલણ",
        "રસીદ",
        "બિલ બનાવો",
        "બિલ બનાવી આપો",
        "ઇનવોઇસ",
    ),
    "store": (
        "store ka name",
        "store ka naam",
        "store name",
        "store naam",
        "mere store",
        "mera store",
        "my store",
        "kitane store",
        "kitne store",
        "kitna store",
        "how many store",
        "how many stores",
        "total store",
        "total stores",
        "stores list",
        "store list",
        "saare store",
        "saare stores",
        "all stores",
        "active store",
        "store ki category",
        "store category",
        "store ka category",
        "meri category",
        "mere store ki category",
        "category kya",
        "category batao",
        "category ke according",
        "category ke accrding",
        "category according",
        "kaunse product",
        "konsa product",
        "kya product",
        "product suggest",
        "products suggest",
        "product suggestion",
        "kya stock karu",
        "kya stock karna",
        "store karne chahiye",
        "stock karne chahiye",
        "kya rakhu",
        "kya rakhna",
    ),
    "customer_stats": (
        "total customer",
        "total customers",
        "kitne customer",
        "kitane customer",
        "kitna customer",
        "kitne customers",
        "kitane customers",
        "how many customer",
        "how many customers",
        "customer count",
        "customers count",
        "customer total",
        "customers total",
        "aaj ke customer",
        "aaj ke customers",
        "today customer",
        "today customers",
        "new customer",
        "new customers",
        "naye customer",
        "naye customers",
    ),
    "invoice_stats": (
        "total invoice",
        "total invoices",
        "total bill",
        "total bills",
        "kitne invoice",
        "kitane invoice",
        "kitna invoice",
        "kitne bill",
        "kitane bill",
        "kitna bill",
        "how many invoice",
        "how many invoices",
        "how many bill",
        "how many bills",
        "invoice count",
        "invoices count",
        "bill count",
        "bills count",
        "aaj ki invoice",
        "aaj ke invoice",
        "aaj ka invoice",
        "aaj ki bill",
        "aaj ke bill",
        "today invoice",
        "todays invoice",
        "today's invoice",
        "today invoices",
        "todays invoices",
        "today's invoices",
        "today bill",
        "todays bill",
        "today's bill",
        "last 7 day",
        "last 7 days",
        "last7 day",
        "last7 days",
        "last seven day",
        "last seven days",
        "pichle 7 din",
        "pichhle 7 din",
        "7 din ki invoice",
        "7 din ke invoice",
        "7 days invoice",
        "7 day invoice",
        "hafta invoice",
        "hafte ki invoice",
        "hafte ke bill",
        "weekly invoice",
        "weekly bill",
        "last 15 day",
        "last 15 days",
        "last 30 day",
        "last 30 days",
        "pichle 30 din",
        "is mahine",
        "is month",
        "this month",
        "total sell",
        "sell kitni",
        "sell kitna",
        "total revenue",
        "revenue",
        "total profit",
        "profit",
        "munafa",
    ),
    "stock_items": (
        "stock items",
        "stock item",
        "item wise stock",
        "inventory items",
        "inventory rows",
        "stock details",
        "stock report",
        "stock breakdown",
        "har product ka stock",
        "products ka stock",
        "saare items ka stock",
        "stock list",
    ),
    "invoices": (
        "invoice list",
        "invoices list",
        "list invoice",
        "list invoices",
        "bill list",
        "bills list",
        "recent invoices",
        "recent bills",
        "purane bill",
        "purane invoices",
        "invoices dikhao",
        "bills dikhao",
        "saare bill",
        "saare invoices",
        "bill history",
    ),
    "expense": (
        "expense",
        "expenses",
        "kharcha",
        "kharche",
        "kharch",
        "expense list",
        "expenses list",
        "expense summary",
        "kitna kharcha",
        "kitne kharche",
        "total kharcha",
        "total expenses",
        "kharche dikhao",
        "aaj ka kharcha",
        "pichle kharche",
        "expense report",
        "ખર્ચ",
        "ખર્ચા",
        "રોજના ખર્ચા",
        "ખર્ચ લિસ્ટ",
        "ટોટલ ખર્ચ",
    ),
    "cashbook": (
        "cashbook",
        "cash book",
        "galla",
        "galle",
        "galle ka hisaab",
        "galla hisab",
        "cash in",
        "cash out",
        "cash balance",
        "opening balance cash",
        "closing balance cash",
        "daily cash",
        "aaj ka cash",
    ),
    "supplier": (
        "supplier",
        "suppliers",
        "vendor",
        "vendors",
        "supplier summary",
        "supplier list",
        "suppliers list",
        "supplier dhundo",
        "supplier ka phone",
        "supplier dues",
        "supplier payable",
        "supplier ka hisab",
        "vendors list",
    ),
    "purchase_order": (
        "purchase order",
        "purchase orders",
        "po list",
        "pos list",
        "po dikhao",
        "list po",
        "pending po",
        "approved po",
        "kharidari order",
        "purchase order status",
        "po status",
        "po create",
        "create po",
        "po banana",
        "po banao",
        "po bana",
        "po create krna",
        "purchase order create",
        "purchase order banao",
        "purchase order bana",
    ),
    "bill": (
        "bill summary",
        "bills summary",
        "purchase bill",
        "purchase bills",
        "supplier bill",
        "supplier bills",
        "overdue bills",
        "pending bills",
        "kitne bill baki",
        "bill status",
    ),
    "gst": (
        "gst summary",
        "gst report",
        "gst return",
        "gst tax",
        "gst health",
        "tax summary",
        "tax report",
        "sales gst",
        "purchase gst",
        "input tax",
        "output tax",
        "cgst",
        "sgst",
        "igst",
        "gst score",
    ),
    "sales_order": (
        "sales order",
        "sales orders",
        "so list",
        "sos list",
        "sales order list",
        "sales order status",
        "order list",
        "orders list",
        "customer orders",
        "orders dikhao",
    ),
    "staff": (
        "staff",
        "staff list",
        "staff members",
        "employees",
        "employee",
        "karamchari",
        "kaam karne wale",
        "team members",
        "kitne staff",
        "kaun kaun kaam karta",
    ),
    "detailed_analytics": (
        "detailed analytics",
        "growth analytics",
        "customer growth",
        "sales trend",
        "sales trends",
        "demand zyada",
        "kab demand",
        "demand kab",
        "cohort",
        "detailed report",
        "30 din ka trend",
        "15 din ka trend",
        "7 din ka trend",
        "7 ya 30 dino",
        "7 ya 30 din",
    ),
    "business_advisor": (
        "dhandha badhane",
        "dhandha karne me",
        "dhandha badhao",
        "business badhane",
        "business badhao",
        "business grow",
        "sales aur stock",
        "sales and stock",
        "stock aur sales",
        "stock and sales",
        "sales dekh kar guide",
        "stock bhi and all",
        "stock and all",
        "store guide",
        "business guide",
        "dukan badhane",
        "sales badhane",
        "store audit",
        "business overview",
        "shop overview",
        "store overview",
        "business summary",
        "store summary",
        "improve my shop",
        "improve shop",
        "improve business",
        "business kaisa",
        "kaisa chal raha hai",
        "dukan ka overview",
        "shop performance",
        "store performance",
        "what should i do",
        "help me improve",
        "ધંધાની સ્થિતિ",
        "દુકાનની પ્રગતિ",
    ),
    "sales_pareto": (
        "sales pareto",
        "pareto",
        "80 20",
        "80-20",
        "80/20",
        "top products",
        "top selling products",
        "best selling products",
        "highest revenue products",
        "top sellers",
        "top items",
        "sabse jyada bikne wale",
        "sabse jyada bikne wala",
        "top bikne wale",
        "top bikne wala",
        "sabse jyada revenue",
        "sabse jyada kamai wala product",
        "best seller product",
        "sabse upar bikne wale",
        "top product batao",
        "top 5 product",
        "top 10 product",
        "સૌથી વધુ વેચાતી વસ્તુઓ",
        "સૌથી વધુ વેચાણ",
        "sau thi vadhu vechan",
        "top vechatu",
    ),
    "payment_mix": (
        "payment mix",
        "payment breakdown",
        "cash vs upi",
        "payment mode breakdown",
        "collection breakdown",
        "collection mix",
        "kitna cash kitna upi",
        "cash aur upi",
        "cash kitna upi kitna",
        "payment ka hisaab",
        "payment mode",
        "collection kisme aayi",
        "rokad kitna upi kitna",
        "online vs cash",
        "રોકડ અને યુપીઆઈ",
        "ચુકવણીનું વિભાજન",
        "rokad ane upi",
        "rokda ane upi",
    ),
    "inventory_velocity": (
        "inventory velocity",
        "stock velocity",
        "slow moving stock",
        "slow moving items",
        "dead stock",
        "zero sales stock",
        "unsold stock",
        "konta maal nahi bik raha",
        "kaun sa maal nahi bik raha",
        "koun sa maal nahi bik raha",
        "saman nahi bik raha",
        "kaun sa item nahi bika",
        "zero sale item",
        "slow moving maal",
        "dead stock batao",
        "કયો માલ વેચાતો નથી",
        "ધીમે વેચાતો માલ",
        "kayo maal nathi vechato",
    ),
    "store_brief": (
        "store brief",
        "daily brief",
        "daily summary",
        "store summary",
        "today summary",
        "shop summary",
        "store health",
        "morning briefing",
        "aaj ka hisaab",
        "aaj ka hisab",
        "dukaan ka hisaab",
        "dukan ka hisab",
        "store ka hisab",
        "aaj ka pura hisab",
        "din ka hisaab",
        "aaj ka report",
        "subah ka report",
        "આજનો હિસાબ",
        "દુકાનનો હિસાબ",
        "aaj no hisab",
        "aaj nu hisab",
        "dukaan no hisab",
    ),
}

_HOW_TO_CUES = (
    "kaise",
    "kaisein",
    "karein",
    "karu",
    "how to",
    "how do i",
    "how do we",
    "steps",
    "guide",
    "policy",
    "terms",
    "rules",
)

_NEITHER_RE = re.compile(
    r"^(hi|hy|hii+|hello|helo|hlo|hey|yo|thanks|thank you(?:\s+bhai)?|thank u|"
    r"theek hai|thik hai|ok|okay|accha|achha|got it|samajh gaya|dhanyawad|shukriya|"
    r"kem cho|namaste|namaskar|pranam|radhe radhe|ram ram|kya haal hai|kaise ho|"
    r"bye|alvida|good night|good morning|good afternoon|good evening)\W*$",
    re.IGNORECASE,
)

_FAMILY_RES = {
    name: re.compile(
        "|".join(re.escape(cue) for cue in cues),
        re.IGNORECASE,
    )
    for name, cues in _FAMILY_CUES.items()
}
_HOW_TO_RE = re.compile(
    "|".join(re.escape(cue) for cue in _HOW_TO_CUES),
    re.IGNORECASE,
)
_APP_DOC_QUERY_RE = re.compile(
    r"\b(dragbizz|dragai|drag\s*ai|dragorbit)\b|"
    r"\b(zoho|odoo)\b|"
    r"\b(tally\s+vs|vs\s+tally|tally\s+se\s+achha|tally\s+etc|tally\s+se\s+alag)\b|"
    r"\b(kya hai|what is|why use|kyo use|kyu use|kyun use|why should i use)\b|"
    r"\b(features|plans|pricing|subscription|comparison)\b",
    re.IGNORECASE,
)
_GENERIC_CONCEPT_QUERY_RE = re.compile(r"\b(kya hai|what is)\b", re.IGNORECASE)
_APP_BRAND_OR_DOC_TOPIC_RE = re.compile(
    r"\b(dragbizz|dragai|drag\s*ai|dragorbit|zoho|odoo|tally|"
    r"features|plans|pricing|subscription|comparison)\b",
    re.IGNORECASE,
)
_STORE_PROFILE_LOOKUP_RE = re.compile(
    r"\b(?:store\s+(?:(?:ka|ki|ke)\s+)?(?:name|naam|category)|"
    r"my\s+store\s+(?:(?:name|category)|ki\s+category)|"
    r"store\s+(?:name|category)|"
    r"how\s+many\s+stores?|(?:kitne|kitane|kitna)\s+stores?|"
    r"total\s+stores?|all\s+stores?|stores?\s+list|"
    r"category\s+(?:kya|batao|ke\s+according))\b",
    re.IGNORECASE,
)


def _is_app_document_query(text: str) -> bool:
    """Avoid treating a store-profile lookup as product documentation."""
    if not _APP_DOC_QUERY_RE.search(text):
        return False
    return not (
        _GENERIC_CONCEPT_QUERY_RE.search(text)
        and _FAMILY_RES["store"].search(text)
        and not _APP_BRAND_OR_DOC_TOPIC_RE.search(text)
    )


_EXPOSURE_RES = tuple(
    (
        re.compile(
            "|".join(re.escape(cue) for cue in cues),
            re.IGNORECASE,
        ),
        names,
    )
    for cues, names in _EXPOSURE
)

# Sensitive tools need explicit user wording before staging.
_SENSITIVE_ACTION_CUES: dict[str, tuple[str, ...]] = {
    "release_invoice": (
        *tuple(cue for cue in _FAMILY_CUES["invoice"] if cue.startswith("release")),
        "release",
    ),
    "ledger_credit": (
        "ledger credit",
        "jama karo",
        "jama kar diya",
        "jama kar",
        "jama diya",
        "jama de diya",
        "jama daal",
        "jama dalo",
        "jama add",
        "payment record",
        "payment add",
        "payment mila",
        "payment liya",
        "paid karo",
        "khata jama",
        "credit add",
        "jama",
        "payment",
    ),
    "ledger_debit": (
        "ledger debit",
        "udhaar add",
        "udhaar dalo",
        "udhar add",
        "udhar dalo",
        "udhaar le",
        "udhar le",
        "udhaar laga",
        "udhar laga",
        "mere se udhaar",
        "mere se udhar",
        "khate me add",
        "khata me add",
        "khate mein add",
        "khata mein add",
        "khate me daal",
        "khata me daal",
        "due add",
        "debit add",
        "udhaar",
        "udhar",
        "debit",
    ),
    "add_stock": (
        "stock add",
        "add stock",
        "stock badhao",
        "stock badha",
        "stock daalo",
        "stock dalo",
        "stock daal",
        "stock me add",
        "stock mein add",
        "stock me daal",
        "stock mein daal",
        "inventory add",
        "add inventory",
        "unit add",
        "units add",
        "units daalo",
        "units dalo",
        "stock in",
        "stock intake",
        "maal aaya",
        "maal add",
        "stock update",
        "liye the",
        "liya tha",
        "se liye",
        "se liya",
    ),
    "merge_customers": (
        "merge customer",
        "merge customers",
        "customer merge",
        "duplicate merge",
        "merge duplicate",
        "customers merge",
        "merge karo",
        "merge kar do",
    ),
    "set_opening_balance": (
        "opening balance",
        "set opening balance",
        "opening balance set",
        "khata opening",
        "opening khata",
        "shuruati balance",
        "opening due",
    ),
    "record_customer_payment": (
        "formal payment",
        "structured payment",
        "invoice payment",
        "payment entry",
        "upi payment record",
        "cash payment record",
        "bank payment record",
    ),
    "update_customer_payment": (
        "update payment note",
        "payment note update",
        "payment notes",
        "edit payment",
    ),
    "create_collect_link": (
        "collect link",
        "payment link",
        "payment collect",
        "collect payment link",
        "create collect link",
        "payment link banao",
        "collect link banao",
    ),
    "send_payment_reminder": (
        "payment reminder",
        "send reminder",
        "reminder bhejo",
        "reminder send",
        "due reminder",
        "payment yaad dilao",
        "khata reminder",
    ),
    "create_expense": (
        "add kharcha",
        "kharcha add",
        "add karo kharcha",
        "add karo kharche",
        "kharche me add",
        "kharcha me add",
        "add expense",
        "expense add",
        "kharcha record",
        "record expense",
        "kharcha dalo",
        "kharcha daalo",
        "kharcha likho",
        "kharcha banao",
        "rent diya",
        "kiraya diya",
        "bill bhara",
        "bill bhra",
        "light bill",
        "bijli bill",
        "electricity bill",
        "kharcha hua",
    ),
    "create_purchase_order": (
        "create purchase order",
        "draft purchase order",
        "new purchase order",
        "make purchase order",
        "purchase order create",
        "purchase order draft",
        "create po",
        "draft po",
        "new po",
        "po create",
        "po draft",
        "po banao",
        "purchase order banao",
        "order from supplier",
        "supplier order",
        "maal order",
        "stock order",
        "સામાન ઓર્ડર",
        "પરચેસ ઓર્ડર",
    ),
}
_SENSITIVE_ACTION_RES = {
    name: re.compile("|".join(re.escape(cue) for cue in cues), re.IGNORECASE)
    for name, cues in _SENSITIVE_ACTION_CUES.items()
    if cues
}

# Amount may sit between "khate me" and "add" ("khate me 100 add kar do").
_LEDGER_DEBIT_FLEX_RE = re.compile(
    r"khate?\s+me(?:in)?\s+(?:\S+\s+){0,4}(?:add|daal|dalo)\b"
    r"|(?:add|daal|dalo)\s+(?:kar(?:o|u|un|oon| do| dena)?)?\s*"
    r".{0,24}\b(?:khata|khate|udhaar|udhar)\b"
    r"|\bmere\s+se\s+udha?ar\b",
    re.IGNORECASE,
)
_LEDGER_CREDIT_FLEX_RE = re.compile(
    r"khate?\s+me(?:in)?\s+(?:\S+\s+){0,4}(?:jama|payment|paid)\b"
    r"|(?:jama|payment|paid)\s+(?:\S+\s+){0,4}\b(?:khata|khate)\b"
    r"|\bjama\s+k(?:ar|r)(?:o|na|\s+do|\s+dena)?\b",
    re.IGNORECASE,
)
_PO_FLEX_RE = re.compile(
    r"\b(?:po|purchase\s*order)\b.{0,60}\b(?:banao|banaye|bana\s*do|bana\s*dena|create|draft|generate|order|karo|kar\s*do)\b"
    r"|\b(?:banao|banaye|bana\s*do|create|draft|generate)\b.{0,60}\b(?:po|purchase\s*order)\b"
    r"|\b(?:maal|stock|saman|samaan|order)\b.{0,30}\b(?:supplier\s*se\s*mangwa|supplier\s*se\s*order)\b",
    re.IGNORECASE,
)
_PURCHASE_RANK_RE = re.compile(
    r"(?:jyada|zyada).{0,40}(?:saman|samaan|purchase|khareed|liya)"
    r"|(?:kitn[ae]).{0,40}purchase|purchase.{0,40}kitn"
    r"|\b(?:top|best|high|highest)\s+(?:spending|buyer|buyers|spender|spenders)\b"
    r"|\b(?:spending|spend)\s+(?:customers?|grahak)\b",
    re.IGNORECASE,
)
# Amount/name may sit between "stock me" and "add" ("stock me 10 add kar do").
_STOCK_ADD_FLEX_RE = re.compile(
    r"stock\s+me(?:in)?\s+(?:\S+\s+){0,6}(?:add|daal|dalo|badha)\b"
    r"|(?:add|daal|dalo|badha)\s+(?:\S+\s+){0,4}\bstock\b"
    r"|\b(?:unit|units)\s+(?:\S+\s+){0,4}(?:add|daal|dalo)\b"
    r"|\b(?:liye|liya)\s+(?:the|tha|thi)\b"
    r"|\bse\s+liye?\b",
    re.IGNORECASE,
)
_EXPENSE_ADD_FLEX_RE = re.compile(
    r"\b(?:add|daal|dalo|likh(?:o|a)?|record|banao)\s+(?:karo\s+|do\s+)?(?:\S+\s+){0,4}(?:kharch[aeo]|expe?n[sc]e|exepnse)\b"
    r"|\b(?:kharch[aeo]|expe?n[sc]e|exepnse)\s*(?:me(?:in)?)?\s+(?:\S+\s+){0,6}(?:add|daal|dalo|likh(?:o|a)?|record|karo)\b"
    r"|(?:ઉમેરો|નોંધો|લખો|કરો|એડ)\s*(?:કરો\s+)?(?:\S+\s+){0,4}(?:ખર્ચ[ઓા]?)(?:\b|\s|$|[^\w])"
    r"|(?:ખર્ચ[ઓા]?)\s*(?:માં)?\s+(?:\S+\s+){0,6}(?:ઉમેરો|નોંધો|લખો|કરો|એડ)(?:\b|\s|$|[^\w])"
    r"|\b(?:rent|kiraya)\s+(?:\S+\s+){0,3}(?:diya|bhara|bhra|pay)\b"
    r"|(?:ભાડું|ભાડુ)\s+(?:\S+\s+){0,3}(?:આપ્યું|ભર્યું|ચુકવ્યું|આપ્યુ|ભર્યુ)(?:\b|\s|$|[^\w])"
    r"|\b(?:light|bijli|electricity|water|pani|wifi|phone|gas)\s+(?:ka\s+)?bill\b"
    r"|\bbill\s+(?:\S+\s+){0,2}(?:bhara|bhra|diya|pay)\b"
    r"|બિલ\s+(?:\S+\s+){0,2}(?:ભર્યું|આપ્યું|ભર્યુ|આપ્યુ)(?:\b|\s|$|[^\w])"
    r"|\b(?:store|dukaan|shop)\s+ka\s+rent\b"
    r"|(?:દુકાન|સ્ટોર)\s*(?:નું|નો)\s*ભાડું(?:\b|\s|$|[^\w])",
    re.IGNORECASE,
)
_EXPENSE_UPDATE_FLEX_RE = re.compile(
    r"\b(?:update|badal|badlo|change|edit|correct)\b.*?"
    r"\b(?:expense|kharch[aeo]|bill|payment|status)\b"
    r"|\b(?:expense|kharch[aeo]|bill|payment|status)\b.*?"
    r"\b(?:update|badal|badlo|change|edit|correct)\b"
    r"|\b(?:overdue|pending|paid|unpaid|cancel(?:led)?)\b.*?"
    r"\b(?:karo|kar do|mark|status|update|h(?:ai|e))\b"
    r"|\b(?:karo|kar do|mark|update)\b.*?"
    r"\b(?:overdue|pending|paid|unpaid|cancel(?:led)?)\b"
    r"|\biska\s+(?:payment\s+)?(?:status\s+)?(?:overdue|pending|paid|unpaid|cancel(?:led)?)\b"
    r"|\b(?:yeh|iska|iski)\s+update\s+karo\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TurnIntent:
    routing: RoutingLabel
    tool_names: frozenset[str]


_NEGATION_ACTION_RE = re.compile(
    r"\b(?:do\s*not|don\'?t|never|mat|nahi|nahin|cancel|stop|nhi)\s+"
    r"(?:create|add|banao|update|edit|delete|remove|record|release|send|link|merge|set)\b"
    r"|\b(?:create|add|banao|update|edit|delete|remove|record|release|send|link|merge|set)\b\s+"
    r"(?:mat|nahi|nahin|nhi)\b",
    re.IGNORECASE,
)


def _exposure_tools(text: str) -> set[str]:
    if _NEGATION_ACTION_RE.search(text):
        return set()
    names: set[str] = set()
    for pattern, tools in _EXPOSURE_RES:
        if pattern.search(text):
            names |= tools
    if _LEDGER_DEBIT_FLEX_RE.search(text):
        names.add("ledger_debit")
    if _LEDGER_CREDIT_FLEX_RE.search(text):
        names.add("ledger_credit")
    if _PURCHASE_RANK_RE.search(text):
        names.add("top_customers")
    if _STOCK_ADD_FLEX_RE.search(text):
        names.update({"add_stock", "search_product"})
    if _EXPENSE_ADD_FLEX_RE.search(text):
        names.add("create_expense")
    if _EXPENSE_UPDATE_FLEX_RE.search(text):
        names.add("update_expense")
    if _PO_FLEX_RE.search(text):
        names.update({"create_purchase_order", "search_supplier", "search_product"})

    # System-wide hybrid typo-tolerant write tool discovery
    candidates = GLOBAL_TOOL_RETRIEVER.retrieve_candidates(
        text,
        available_tools=TOOL_METADATA_CATALOG.keys(),
        limit=10,
    )
    for c in candidates:
        if c.score >= 12.0:
            meta = TOOL_METADATA_CATALOG.get(c.tool_name)
            if meta is not None and meta.action_type in {
                ActionType.CREATE,
                ActionType.UPDATE,
                ActionType.DELETE,
            }:
                names.add(c.tool_name)

    return names


def _prior_exposure_tools(prior_user_texts: Sequence[str] | None) -> set[str]:
    if not prior_user_texts:
        return set()
    names: set[str] = set()
    for text in prior_user_texts[-_PRIOR_EXPOSURE_TURNS:]:
        if isinstance(text, str) and text.strip():
            names |= _exposure_tools(text)
    return names


_WHO_IS_RE = re.compile(
    r"poori details|full details|complete details|all details|"
    r"sab details|sab kuch|pura profile|poora profile|entire profile|"
    r"kon he|kaun hai|kaun he|kon hai|who is|"
    r"ke baare me(?!in)|ke bare me(?!in)",
    re.IGNORECASE,
)
_WHO_IS_TOOLS = frozenset({"customer_dossier", "search_product"})
_WHO_IS_PHONE_RE = re.compile(r"\b([6-9]\d{9})\b")
_WHO_IS_FILLER_RE = re.compile(
    r"^(?:please|pls|bhai|mujhe|batao|bata|yeh|ye|yah)\s+",
    re.IGNORECASE,
)


def extract_who_is_query(question: str) -> str | None:
    """Name or phone from a who-is question. None when no subject remains."""
    text = question.strip()
    if not text or not _WHO_IS_RE.search(text) or _APP_DOC_QUERY_RE.search(text):
        return None
    phone = _WHO_IS_PHONE_RE.search(text)
    if phone:
        return phone.group(1)
    cleaned = _WHO_IS_RE.sub(" ", text)
    cleaned = re.sub(r"[?.,:;!\"'`“”‘’]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    while True:
        nxt = _WHO_IS_FILLER_RE.sub("", cleaned).strip()
        if nxt == cleaned:
            break
        cleaned = nxt
    if len(cleaned) < 2:
        return None
    return cleaned[:200]


_PURE_CHITCHAT_RE = re.compile(
    r"^(?:(?:hi+|hello+|hey+|hola|namaste)\s*)?"
    r"(?:kaise\s+ho|kya\s+haal\s+hai?|kem\s+cho|how\s+are\s+you|"
    r"hi+|hello+|hey+|hola|namaste|"
    r"good\s+(?:morning|afternoon|evening|night)|"
    r"thank\s*(?:you|s)?|dhanyawad|shukriya|thx|"
    r"who\s+(?:are\s+you|made\s+you)|what\s+can\s+you\s+do|aap\s+kaun\s+ho|tum\s+kaun\s+ho|"
    r"bye+|alvida|tata|see\s+you|"
    r"ok|okay|theek\s+hai|achha|sahi\s+hai|cool|nice|great|sure)"
    r"(?:\s+(?:bhai|bro(?:ther)?|sir|ji|friend|dost|all))?[.!?\s]*$",
    re.IGNORECASE,
)

_STORE_OPERATIONAL_CUES_RE = re.compile(
    r"\b(sale|sales|bikri|invoice|bill|stock|inventory|maal|saman|saaman|"
    r"product|item|supplier|vendor|purchase|po\b|order|customer|grahak|"
    r"khata|udhaar|udhari|jama|baki|due|balance|ledger|expense|kharcha|kharch|"
    r"cashbook|galla|counter\s+cash|staff|store|dukan|dukaan|gst|tax|"
    r"price|rate|cost|profit|rupaye|rs\.?|₹|\d+\s*(qty|packet|kg|gm|piece|box|nag))\b",
    re.IGNORECASE,
)

_DOMAIN_PATTERNS: dict[ToolDomain, re.Pattern[str]] = {
    ToolDomain.INVENTORY: re.compile(
        r"\b(stock|inventory|maal|saman|saaman|product|item|items|sku|godown|"
        r"godam|velocity|low\s+stock|out\s+of\s+stock|maal\s+aya|stock\s+add|"
        r"item\s+add|inventory\s+velocity|products?)\b",
        re.IGNORECASE,
    ),
    ToolDomain.PROCUREMENT: re.compile(
        r"\b(supplier|suppliers|vendor|vendors|purchase\s+order|po\b|"
        r"order\s+from\s+supplier|supplier\s+se|purane\s+bill|kharidari|"
        r"purchase\s+bill|po\s+create|po\s+banao|po\s+banana|po\s+bana|"
        r"po\s+draft|draft\s+po|maal\s+order)\b",
        re.IGNORECASE,
    ),
    ToolDomain.SALES: re.compile(
        r"\b(sale|sales|bikri|invoice|invoices|challan|sales\s+order|pareto|"
        r"becha|bechi|parchi|create\s+invoice|draft\s+invoice|bill\s+bana|"
        r"bill\s+kata|aaj\s+ki\s+sale|today\s+sale|revenue)\b",
        re.IGNORECASE,
    ),
    ToolDomain.KHATA: re.compile(
        r"\b(customer|customers|grahak|khata|udhaar|udhari|jama|baki|due|dues|"
        r"payment|payments|reminder|reminders|collect\s+link|ledger|hisab|"
        r"hisaab|account|accounts|party)\b",
        re.IGNORECASE,
    ),
    ToolDomain.FINANCE: re.compile(
        r"\b(expense|expenses|kharcha|kharch|cashbook|galla|counter\s+cash|"
        r"petrol|diesel|rent|kiraya|bijli|electricity|water|salary|pagar|"
        r"wages|chai|nashta|gst|tax)\b",
        re.IGNORECASE,
    ),
    ToolDomain.GENERAL: re.compile(
        r"\b(staff|karamchari|employees?|brief|daily\s+brief|store\s+brief|"
        r"overview|dukan\s+ka|dukaan|store\s+overview|all\s+stores)\b",
        re.IGNORECASE,
    ),
}


_CONVERSATIONAL_ACK_RE = re.compile(
    r"^(?:thik\s*h(?:ai|e)|theek\s*h(?:ai|e)|ok|okay|achha|accha|sahi\s*h(?:ai|e))\b.*?"
    r"\b(?:ruk|ruko|rehne\s*do|rahne\s*do|baad\s*me|cancel|chodo|chhod\s*do|samajh\s*gaya|got\s*it)\b"
    r"|^(?:ruk|ruko|rehne\s*do|rahne\s*do|chodo|chhod\s*do|baad\s*me\s*karenge|kuch\s*nahi)\b",
    re.IGNORECASE,
)


def is_pure_chitchat(text: str) -> bool:
    """True if query is conversational chit-chat with zero store operational intent."""
    cleaned = text.strip()
    if not cleaned:
        return False
    if _STORE_OPERATIONAL_CUES_RE.search(cleaned):
        return False
    return bool(
        _PURE_CHITCHAT_RE.match(cleaned)
        or _NEITHER_RE.match(cleaned)
        or _CONVERSATIONAL_ACK_RE.search(cleaned)
    )


def detect_query_domains(text: str) -> set[ToolDomain]:
    """Detect store operational domains relevant to the user query."""
    domains: set[ToolDomain] = set()
    cleaned = text.strip()
    if not cleaned:
        return domains

    for domain, pattern in _DOMAIN_PATTERNS.items():
        if pattern.search(cleaned):
            domains.add(domain)

    if any(
        _FAMILY_RES[k].search(cleaned)
        for k in ("stock", "stock_items", "product", "product_stats")
    ):
        domains.add(ToolDomain.INVENTORY)
    if any(
        _FAMILY_RES[k].search(cleaned) for k in ("supplier", "purchase_order", "bill")
    ):
        domains.add(ToolDomain.PROCUREMENT)
    if any(
        _FAMILY_RES[k].search(cleaned)
        for k in ("sale", "invoice", "invoices", "invoice_stats", "sales_order")
    ):
        domains.add(ToolDomain.SALES)
    if any(
        _FAMILY_RES[k].search(cleaned)
        for k in (
            "customer",
            "customer_ledger",
            "customer_accounts",
            "customer_stats",
            "payment",
            "payment_detail",
            "payment_reminders",
        )
    ):
        domains.add(ToolDomain.KHATA)
    if any(_FAMILY_RES[k].search(cleaned) for k in ("expense", "cashbook", "gst")):
        domains.add(ToolDomain.FINANCE)
    if any(
        _FAMILY_RES[k].search(cleaned)
        for k in ("staff", "store_brief", "detailed_analytics")
    ):
        domains.add(ToolDomain.GENERAL)

    # Hybrid typo-tolerant retrieval domain signals
    candidates = GLOBAL_TOOL_RETRIEVER.retrieve_candidates(
        cleaned,
        available_tools=TOOL_METADATA_CATALOG.keys(),
        limit=6,
    )
    for c in candidates:
        if c.score >= 12.0 or c.alias_match:
            meta = TOOL_METADATA_CATALOG.get(c.tool_name)
            if meta is not None:
                domains.add(meta.domain)

    return domains


def resolve_domain_turn_intent(
    question: str,
    *,
    available: Iterable[str],
    prior_user_texts: Sequence[str] | None = None,
) -> TurnIntent:
    available_set = frozenset(available)
    text = question.strip()
    if not text:
        return TurnIntent(
            routing="unknown",
            tool_names=SAFE_BROAD_STORE_FALLBACK & available_set,
        )

    # 1. Pure Chit-Chat -> 0 tools, routing="neither"
    if is_pure_chitchat(text):
        return TurnIntent(routing="neither", tool_names=frozenset())

    has_howto = bool(_HOW_TO_RE.search(text) or _is_app_document_query(text))
    if _STORE_PROFILE_LOOKUP_RE.search(text):
        tool_names = frozenset({"list_stores"} & available_set)
        routing: RoutingLabel = "both" if has_howto else "tools"
        return TurnIntent(routing=routing, tool_names=tool_names)

    domains = detect_query_domains(text)

    # 2. Domains matched -> expose full domain bundles + write cues
    if domains:
        bundle_tools: set[str] = set()
        for domain in domains:
            bundle_tools |= DOMAIN_READ_BUNDLES.get(domain, frozenset())

        carried = _prior_exposure_tools(prior_user_texts)
        current_writes = _exposure_tools(text)
        if ("create_expense" in carried or "update_expense" in carried) and re.search(
            r"\b(overdue|pending|paid|unpaid|update|badal|badlo|change|cancel)\b",
            text,
            re.IGNORECASE,
        ):
            current_writes.add("update_expense")

        tool_names = (
            bundle_tools
            | current_writes
            | (
                carried
                & {
                    "create_expense",
                    "update_expense",
                    "create_invoice_draft",
                    "update_invoice_draft",
                }
            )
        ) & available_set

        routing: RoutingLabel = "both" if has_howto else "tools"
        return TurnIntent(routing=routing, tool_names=frozenset(tool_names))

    # 3. No store domain matched: check if pure how-to / docs query
    if has_howto:
        return TurnIntent(routing="docs", tool_names=frozenset())

    # 4. Ambiguous or unfamiliar store-related request ->
    # Safe broad fallback (READ only)
    carried = _prior_exposure_tools(prior_user_texts)
    current_writes = _exposure_tools(text)
    tool_names = (SAFE_BROAD_STORE_FALLBACK | carried | current_writes) & available_set
    return TurnIntent(routing="unknown", tool_names=frozenset(tool_names))


def resolve_turn_intent(
    question: str,
    *,
    available: Iterable[str],
    prior_user_texts: Sequence[str] | None = None,
    use_domain_routing: bool = False,
) -> TurnIntent:
    if use_domain_routing:
        return resolve_domain_turn_intent(
            question,
            available=available,
            prior_user_texts=prior_user_texts,
        )
    available_set = frozenset(available)
    text = question.strip()
    if not text:
        return TurnIntent(
            routing="unknown",
            tool_names=_CORE_UNKNOWN_TOOLS & available_set,
        )

    matched_reads: set[str] = set()
    for family, pattern in _FAMILY_RES.items():
        if pattern.search(text):
            matched_reads |= _FAMILY_READS[family]

    # Hybrid typo-tolerant retrieval for reads
    if not matched_reads and not _WHO_IS_RE.search(text):
        candidates = GLOBAL_TOOL_RETRIEVER.retrieve_candidates(
            text,
            available_tools=available_set,
            limit=6,
        )
        for c in candidates:
            if c.score >= 12.0 or c.alias_match:
                meta = TOOL_METADATA_CATALOG.get(c.tool_name)
                if meta is not None and meta.action_type in {
                    ActionType.READ,
                    ActionType.SEARCH,
                    ActionType.ANALYTICS,
                }:
                    matched_reads.add(c.tool_name)
                    matched_reads.update(
                        comp for comp in meta.companion_reads if comp in available_set
                    )

    is_neither = is_pure_chitchat(text)
    has_tools = bool(matched_reads) and not is_neither
    has_howto = (
        bool(_HOW_TO_RE.search(text) or _is_app_document_query(text))
        and not is_neither
    )

    if has_tools and has_howto:
        routing: RoutingLabel = "both"
        tool_names = frozenset(matched_reads) & available_set
    elif has_tools:
        routing = "tools"
        carried = _prior_exposure_tools(prior_user_texts)
        current = _exposure_tools(text)
        if ("create_expense" in carried or "update_expense" in carried) and re.search(
            r"\b(overdue|pending|paid|unpaid|update|badal|badlo|change|cancel)\b",
            text,
            re.IGNORECASE,
        ):
            current.add("update_expense")
        tool_names = (
            matched_reads | current | (carried & {"create_expense", "update_expense"})
        ) & available_set
    elif has_howto:
        routing = "docs"
        tool_names = frozenset()
    elif is_neither:
        routing = "neither"
        tool_names = frozenset()
    else:
        routing = "unknown"
        # Keep prior writes + apply current-turn exposure cues.
        carried = _prior_exposure_tools(prior_user_texts)
        current = _exposure_tools(text)
        if ("create_expense" in carried or "update_expense" in carried) and re.search(
            r"\b(overdue|pending|paid|unpaid|update|badal|badlo|change|cancel)\b",
            text,
            re.IGNORECASE,
        ):
            current.add("update_expense")
        tool_names = (_CORE_UNKNOWN_TOOLS | carried | current) & available_set

    write_exposure = _exposure_tools(text) - _READ_TOOLS
    customer_only = matched_reads <= _FAMILY_READS["customer"]
    if (
        _WHO_IS_RE.search(text)
        and not _APP_DOC_QUERY_RE.search(text)
        and not write_exposure
        and not has_howto
        and (not has_tools or customer_only)
    ):
        routing = "tools"
        tool_names = _WHO_IS_TOOLS & available_set

    return TurnIntent(routing=routing, tool_names=tool_names)


def user_requested_sensitive_action(question: str, tool_name: str) -> bool:
    """True if user text itself asks for this sensitive action."""
    text = question.strip()
    if tool_name == "ledger_debit" and _LEDGER_DEBIT_FLEX_RE.search(text):
        return True
    if tool_name == "ledger_credit" and _LEDGER_CREDIT_FLEX_RE.search(text):
        return True
    if tool_name == "add_stock" and _STOCK_ADD_FLEX_RE.search(text):
        return True
    if tool_name == "create_expense" and _EXPENSE_ADD_FLEX_RE.search(text):
        return True
    if tool_name == "create_purchase_order" and _PO_FLEX_RE.search(text):
        return True
    pattern = _SENSITIVE_ACTION_RES.get(tool_name)
    if pattern is not None and pattern.search(text):
        return True

    # Hybrid typo-tolerant sensitive action check
    meta = TOOL_METADATA_CATALOG.get(tool_name)
    if meta is not None:
        candidates = GLOBAL_TOOL_RETRIEVER.retrieve_candidates(
            text, available_tools=TOOL_METADATA_CATALOG.keys(), limit=10
        )
        for c in candidates:
            if c.tool_name == tool_name:
                if (
                    tool_name == "ledger_credit"
                    and not _LEDGER_CREDIT_FLEX_RE.search(text)
                ):
                    continue
                if tool_name == "ledger_debit" and _LEDGER_CREDIT_FLEX_RE.search(text):
                    continue
                if c.alias_match:
                    return True
                if (
                    c.matched_action == meta.action_type
                    and c.matched_entity == meta.entity_type
                    and c.score >= 18.0
                ):
                    return True

    return False


def should_retrieve_docs(
    routing: RoutingLabel,
    *,
    tool_names: frozenset[str] | None = None,
) -> bool:
    """Skip RAG on tool-only turns and write follow-ups."""
    if routing in {"docs", "both"}:
        return True
    if routing != "unknown":
        return False
    return not (tool_names is not None and tool_names - _READ_TOOLS)


_PHONE_RE = re.compile(r"^[\d\s+\-]{8,16}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def looks_like_field_fill(text: str) -> bool:
    """Short name / phone / email replies in multi-turn write flows."""
    value = text.strip()
    if not value or len(value) > 64:
        return False
    if _PHONE_RE.fullmatch(value) or _EMAIL_RE.fullmatch(value):
        return True
    if len(value.split()) > 4:
        return False
    if _HOW_TO_RE.search(value) or _NEITHER_RE.match(value):
        return False
    return all(not pattern.search(value) for pattern in _FAMILY_RES.values())


def narrow_field_fill_tools(tool_names: frozenset[str]) -> frozenset[str]:
    """Keep write tools + minimal companion reads for field-fill turns."""
    writes = tool_names - _READ_TOOLS
    if not writes:
        return tool_names
    companions: set[str] = set()
    if writes & {"create_customer", "update_customer"}:
        companions.add("search_customer")
    if writes & {
        "create_invoice_draft",
        "update_invoice_draft",
        "release_invoice",
    }:
        companions.update({"search_customer", "search_product"})
    if writes & {"ledger_credit", "ledger_debit"}:
        companions.update({"search_customer", "payment_history"})
    if writes & {
        "merge_customers",
        "set_opening_balance",
        "record_customer_payment",
        "create_collect_link",
        "send_payment_reminder",
    }:
        companions.add("search_customer")
    if writes & {"update_customer_payment"}:
        companions.update({"payment_history", "get_customer_payment"})
    if writes & {"add_stock"}:
        companions.add("search_product")
    if writes & {"create_expense", "update_expense"}:
        companions.update({"expense_summary", "list_expenses"})
    if writes & {"create_purchase_order"}:
        companions.update({"search_supplier", "search_product", "list_purchase_orders"})
    return frozenset(writes | (companions & tool_names))
