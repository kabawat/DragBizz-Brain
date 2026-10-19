"""Turn intent: routing label + exposed tools for this message."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

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
        "bill_summary",
        "gst_summary",
        "list_sales_orders",
        "list_staff",
        "customer_detailed_analytics",
        "invoice_detailed_analytics",
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

_FAMILY_READS: dict[str, frozenset[str]] = {
    "sale": frozenset({"today_sale", "invoice_summary"}),
    "stock": frozenset({"stock_summary", "search_product"}),
    "stock_items": frozenset(
        {"stock_items", "stock_summary", "search_product"}
    ),
    "product": frozenset({"search_product"}),
    "product_stats": frozenset({"product_summary"}),
    "payment": frozenset({"payment_history", "search_customer"}),
    "payment_detail": frozenset({"get_customer_payment", "payment_history"}),
    "payment_reminders": frozenset(
        {"list_payment_reminders", "search_customer"}
    ),
    # Lookup/create flows need search only; payment history is payment-family.
    "customer": frozenset({"search_customer"}),
    "customer_ledger": frozenset({"get_customer_ledger", "search_customer"}),
    "customer_accounts": frozenset(
        {"list_customer_accounts", "search_customer"}
    ),
    "customer_stats": frozenset({"customer_summary"}),
    "invoice": frozenset({"search_customer", "search_product"}),
    "invoices": frozenset({"list_invoices", "invoice_summary", "today_sale"}),
    "invoice_stats": frozenset({"invoice_summary", "today_sale"}),
    "expense": frozenset({"expense_summary", "list_expenses"}),
    "cashbook": frozenset({"cashbook_summary", "today_sale"}),
    "supplier": frozenset(
        {"search_supplier", "supplier_summary", "bill_summary"}
    ),
    "purchase_order": frozenset(
        {"list_purchase_orders", "search_supplier", "search_product"}
    ),
    "bill": frozenset({"bill_summary", "supplier_summary", "search_supplier"}),
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
        frozenset({"create_purchase_order"}),
    ),
)

_FAMILY_CUES: dict[str, tuple[str, ...]] = {
    "sale": (
        "aaj ki sale",
        "today's sale",
        "today sale",
        "sale kitni",
        "sale kitna",
        "sale batao",
        "kitne bill",
        "bill bane",
        "bills today",
        "today's bills",
        "total sell",
        "sell kitni",
        "sell kitna",
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
_PURCHASE_RANK_RE = re.compile(
    r"(?:jyada|zyada).{0,40}(?:saman|samaan|purchase|khareed|liya)"
    r"|(?:kitn[ae]).{0,40}purchase|purchase.{0,40}kitn",
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
    r"\b(?:add|daal|dalo|likho|record|banao)\s+(?:karo\s+)?(?:\S+\s+){0,4}(?:kharch[aeo]|expense)\b"
    r"|\b(?:kharch[aeo]|expense)\s*(?:me(?:in)?)?\s+(?:\S+\s+){0,6}(?:add|daal|dalo|likho|record|karo)\b"
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


def _exposure_tools(text: str) -> set[str]:
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
    if not text or not _WHO_IS_RE.search(text):
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


def resolve_turn_intent(
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
            tool_names=_CORE_UNKNOWN_TOOLS & available_set,
        )

    matched_reads: set[str] = set()
    for family, pattern in _FAMILY_RES.items():
        if pattern.search(text):
            matched_reads |= _FAMILY_READS[family]

    has_tools = bool(matched_reads)
    has_howto = bool(_HOW_TO_RE.search(text))
    is_neither = bool(_NEITHER_RE.match(text))

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
    pattern = _SENSITIVE_ACTION_RES.get(tool_name)
    if pattern is None:
        return False
    return bool(pattern.search(text))


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
        companions.update(
            {"search_supplier", "search_product", "list_purchase_orders"}
        )
    return frozenset(writes | (companions & tool_names))
