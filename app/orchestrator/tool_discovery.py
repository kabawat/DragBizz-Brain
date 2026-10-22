from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from app.schemas.tool import ToolAccessType, ToolDomain


class ActionType(str, Enum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ANALYTICS = "analytics"
    SEARCH = "search"


@dataclass(frozen=True)
class ToolRetrievalMetadata:
    name: str
    domain: ToolDomain
    action_type: ActionType
    entity_type: str
    description: str
    aliases: tuple[str, ...] = ()
    companion_reads: tuple[str, ...] = ()


TOOL_METADATA_CATALOG: dict[str, ToolRetrievalMetadata] = {
    # === INVENTORY (6 tools) ===
    "add_stock": ToolRetrievalMetadata(
        name="add_stock",
        domain=ToolDomain.INVENTORY,
        action_type=ActionType.CREATE,
        entity_type="stock",
        description="Stage stock-in for one or more products (needs user confirm).",
        aliases=(
            "add stock", "stock add", "stock in", "stock badhao", "stock dalo", "stock daalo",
            "stock intake", "inventory add", "add inventory", "unit add", "units add",
            "units dalo", "units daalo", "maal aaya", "maal add", "stock me add",
            "stock mein add", "stock badha", "stock update",
        ),
        companion_reads=("search_product", "stock_summary"),
    ),
    "inventory_velocity": ToolRetrievalMetadata(
        name="inventory_velocity",
        domain=ToolDomain.INVENTORY,
        action_type=ActionType.ANALYTICS,
        entity_type="stock",
        description="Deterministic inventory sales velocity and scanning: correlation of stock velocity.",
        aliases=(
            "inventory velocity", "stock velocity", "fast moving items", "slow moving items",
            "moving stock", "stock movement", "velocity report",
        ),
        companion_reads=("stock_summary", "search_product"),
    ),
    "product_summary": ToolRetrievalMetadata(
        name="product_summary",
        domain=ToolDomain.INVENTORY,
        action_type=ActionType.READ,
        entity_type="product",
        description="How many products are listed/created in the catalog (total, active, inactive).",
        aliases=(
            "product summary", "product count", "total products", "kitne product", "products count",
            "catalog count", "catalog summary", "kitne item", "total items",
        ),
        companion_reads=("search_product", "stock_summary"),
    ),
    "search_product": ToolRetrievalMetadata(
        name="search_product",
        domain=ToolDomain.INVENTORY,
        action_type=ActionType.SEARCH,
        entity_type="product",
        description="Search live products by name/SKU (price, stock, status).",
        aliases=(
            "search product", "find product", "product search", "check product", "item search",
            "product details", "product price", "product rate", "saman search", "maal search",
            "product check", "price check", "rate check", "bhav check", "rate batao",
        ),
        companion_reads=("stock_summary",),
    ),
    "stock_items": ToolRetrievalMetadata(
        name="stock_items",
        domain=ToolDomain.INVENTORY,
        action_type=ActionType.READ,
        entity_type="stock",
        description="Itemized inventory stock rows across products and variants (low stock, batch).",
        aliases=(
            "stock items", "list stock items", "item stock", "itemized stock", "batch stock",
            "low stock items", "out of stock items", "stock list", "inventory items",
        ),
        companion_reads=("stock_summary", "search_product"),
    ),
    "stock_summary": ToolRetrievalMetadata(
        name="stock_summary",
        domain=ToolDomain.INVENTORY,
        action_type=ActionType.READ,
        entity_type="stock",
        description="Inventory/stock totals only (qty on hand, low/out of stock).",
        aliases=(
            "stock summary", "stock report", "total stock", "stock status", "inventory summary",
            "inventory status", "kitna maal bacha", "stock kitna", "stock bacha", "stock check",
            "dukaan me stock", "godown stock", "godam me maal",
        ),
        companion_reads=("search_product", "stock_items"),
    ),

    # === SALES (9 tools) ===
    "create_invoice_draft": ToolRetrievalMetadata(
        name="create_invoice_draft",
        domain=ToolDomain.SALES,
        action_type=ActionType.CREATE,
        entity_type="invoice",
        description="Create DRAFT invoice only (no stock deduct). Items need real product ObjectIds.",
        aliases=(
            "create invoice", "create invoice draft", "draft invoice", "make invoice", "make bill",
            "create bill", "bill banao", "invoice banao", "bill bana", "invoice bana",
            "bill for", "naya bill", "new bill", "new invoice", "challan banao",
        ),
        companion_reads=("search_customer", "search_product"),
    ),
    "invoice_detailed_analytics": ToolRetrievalMetadata(
        name="invoice_detailed_analytics",
        domain=ToolDomain.SALES,
        action_type=ActionType.ANALYTICS,
        entity_type="invoice",
        description="Macro trend analytics (revenue trend, growth rates, status breakdown, ticket size).",
        aliases=(
            "invoice analytics", "sales trend", "revenue trend", "ticket size", "growth rate",
            "detailed sales analytics", "sales detailed",
        ),
        companion_reads=("today_sale", "invoice_summary"),
    ),
    "invoice_summary": ToolRetrievalMetadata(
        name="invoice_summary",
        domain=ToolDomain.SALES,
        action_type=ActionType.READ,
        entity_type="invoice",
        description="Invoice/bill counts and amounts. Returns all-time totals, today totals.",
        aliases=(
            "invoice summary", "bill summary", "invoices count", "total invoices", "kitne bill bane",
            "bill report", "invoice report", "total bills", "bills count",
        ),
        companion_reads=("today_sale", "list_invoices"),
    ),
    "list_invoices": ToolRetrievalMetadata(
        name="list_invoices",
        domain=ToolDomain.SALES,
        action_type=ActionType.READ,
        entity_type="invoice",
        description="List invoices/bills with invoiceNumber, customer, date/time and totals.",
        aliases=(
            "list invoices", "list bills", "recent invoices", "recent bills", "purane bill",
            "bills list", "invoices list", "invoices dikhao", "bill dikhao",
        ),
        companion_reads=("invoice_summary", "today_sale"),
    ),
    "list_sales_orders": ToolRetrievalMetadata(
        name="list_sales_orders",
        domain=ToolDomain.SALES,
        action_type=ActionType.READ,
        entity_type="order",
        description="List customer sales orders with order number, customer, status, totals.",
        aliases=(
            "list sales orders", "sales orders", "customer orders", "order list", "orders list",
            "sales order list", "grahak ke order",
        ),
        companion_reads=("list_invoices", "today_sale"),
    ),
    "release_invoice": ToolRetrievalMetadata(
        name="release_invoice",
        domain=ToolDomain.SALES,
        action_type=ActionType.UPDATE,
        entity_type="invoice",
        description="Stage DRAFT release (stock deduct); needs user confirm. Real invoiceId required.",
        aliases=(
            "release invoice", "release draft", "release the draft", "bill release", "final bill",
            "invoice release karo", "bill final karo", "release bill",
        ),
        companion_reads=("list_invoices", "invoice_summary"),
    ),
    "sales_pareto": ToolRetrievalMetadata(
        name="sales_pareto",
        domain=ToolDomain.SALES,
        action_type=ActionType.ANALYTICS,
        entity_type="sales",
        description="Deterministic 80/20 Pareto product sales analysis: calculates cumulative revenue.",
        aliases=(
            "sales pareto", "pareto analysis", "80 20 analysis", "top revenue products",
            "best selling products", "top products", "pareto report",
        ),
        companion_reads=("today_sale", "invoice_summary"),
    ),
    "today_sale": ToolRetrievalMetadata(
        name="today_sale",
        domain=ToolDomain.SALES,
        action_type=ActionType.READ,
        entity_type="sales",
        description="Today's live sales: revenue, profit, bill count.",
        aliases=(
            "today sale", "todays sale", "aaj ki sale", "aaj ka sale", "today sales",
            "sale batao", "sales report", "aaj kitni bikri hui", "aaj ki bikri", "total sale",
            "revenue today", "daily sale", "today revenue",
        ),
        companion_reads=("invoice_summary", "search_product"),
    ),
    "update_invoice_draft": ToolRetrievalMetadata(
        name="update_invoice_draft",
        domain=ToolDomain.SALES,
        action_type=ActionType.UPDATE,
        entity_type="invoice",
        description="Update existing DRAFT: link customer and/or replace items. Pass real invoiceId.",
        aliases=(
            "update invoice", "update invoice draft", "edit invoice", "edit bill", "bill update",
            "invoice update", "draft edit", "bill me item badlo",
        ),
        companion_reads=("create_invoice_draft", "search_product", "search_customer"),
    ),

    # === KHATA (21 tools) ===
    "create_collect_link": ToolRetrievalMetadata(
        name="create_collect_link",
        domain=ToolDomain.KHATA,
        action_type=ActionType.CREATE,
        entity_type="payment",
        description="Stage a payment collect link for a customer (needs confirm).",
        aliases=(
            "create collect link", "collect link", "payment link", "payment collect link",
            "collect payment", "payment link bhejo", "payment link generate", "upi collect link",
        ),
        companion_reads=("search_customer", "get_customer_ledger"),
    ),
    "create_customer": ToolRetrievalMetadata(
        name="create_customer",
        domain=ToolDomain.KHATA,
        action_type=ActionType.CREATE,
        entity_type="customer",
        description="Create customer (name + either phone or email from user). Never invent missing fields.",
        aliases=(
            "create customer", "add customer", "new customer", "naya customer", "customer banao",
            "customer add", "customer create", "add a customer", "create a customer", "add new customer",
            "naya grahak", "grahak jodo", "customer jodo", "customer register", "register customer",
            "crearte customer", "craete customer", "add custmer", "crearte a custiomer",
        ),
        companion_reads=("search_customer",),
    ),
    "customer_detailed_analytics": ToolRetrievalMetadata(
        name="customer_detailed_analytics",
        domain=ToolDomain.KHATA,
        action_type=ActionType.ANALYTICS,
        entity_type="customer",
        description="Detailed periodic customer analytics (growth, acquisition, orders, ticket size).",
        aliases=(
            "customer detailed analytics", "customer analytics", "customer growth", "customer trends",
            "customer report detailed", "customer acquisition",
        ),
        companion_reads=("customer_summary", "top_customers"),
    ),
    "customer_dossier": ToolRetrievalMetadata(
        name="customer_dossier",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="customer",
        description="Who someone is: one customer match plus their saved memo, dues, and payment terms.",
        aliases=(
            "customer dossier", "who is", "kaun hai", "kon he", "poori details", "full profile",
            "customer profile", "pura hisab customer ka", "customer info", "customer history",
        ),
        companion_reads=("search_customer", "get_customer_ledger"),
    ),
    "customer_summary": ToolRetrievalMetadata(
        name="customer_summary",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="customer",
        description="Store customer totals: total customers, today new, and new customers in period.",
        aliases=(
            "customer summary", "total customers", "customer count", "kitne customer",
            "grahak count", "customer report", "total grahak", "kitne grahak hai",
        ),
        companion_reads=("search_customer", "top_customers"),
    ),
    "get_customer_ledger": ToolRetrievalMetadata(
        name="get_customer_ledger",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="ledger",
        description="Standalone khata ledger lines for one customer (running balance, debit, credit).",
        aliases=(
            "customer ledger", "khata ledger", "get customer ledger", "ledger lines", "customer statement",
            "khata statement", "khata hisab", "customer hisab", "ledger hisab", "running balance",
        ),
        companion_reads=("search_customer", "payment_history"),
    ),
    "get_customer_payment": ToolRetrievalMetadata(
        name="get_customer_payment",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="payment",
        description="Fetch one customer payment by payment ObjectId.",
        aliases=(
            "get customer payment", "payment details", "check payment", "payment receipt",
            "single payment", "view payment",
        ),
        companion_reads=("payment_history", "search_customer"),
    ),
    "ledger_credit": ToolRetrievalMetadata(
        name="ledger_credit",
        domain=ToolDomain.KHATA,
        action_type=ActionType.CREATE,
        entity_type="ledger",
        description="Stage customer PAYMENT (khata credit) for user confirm. Real customerId required.",
        aliases=(
            "ledger credit", "jama karo", "jama kar diya", "jama kar", "jama diya", "jama de diya",
            "payment mila", "payment liya", "khata jama", "credit add", "jama add", "payment received",
            "paise mile", "paise jama karo", "khate me jama",
        ),
        companion_reads=("search_customer", "get_customer_ledger"),
    ),
    "ledger_debit": ToolRetrievalMetadata(
        name="ledger_debit",
        domain=ToolDomain.KHATA,
        action_type=ActionType.CREATE,
        entity_type="ledger",
        description="Stage customer DEBIT on khata (increases due) for user confirm. Real customerId required.",
        aliases=(
            "ledger debit", "udhaar add", "udhar add", "udhaar dalo", "udhar dalo", "udhaar diya",
            "udhar diya", "khate me add", "khata me add", "udhaar chadhao", "udhar chadhao",
            "mere se udhaar", "due add", "increase due",
        ),
        companion_reads=("search_customer", "get_customer_ledger"),
    ),
    "list_customer_accounts": ToolRetrievalMetadata(
        name="list_customer_accounts",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="ledger",
        description="List customer khata accounts (dues/advance). Use hasDue=true for dues balance.",
        aliases=(
            "list customer accounts", "customer dues", "customer accounts", "pending dues",
            "baki hisab", "udhari list", "kiska baki hai", "dues list", "total dues", "khata list",
        ),
        companion_reads=("search_customer", "customer_summary"),
    ),
    "list_payment_reminders": ToolRetrievalMetadata(
        name="list_payment_reminders",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="payment",
        description="List payment reminders sent for this store (optional customer filter).",
        aliases=(
            "list payment reminders", "reminders list", "sent reminders", "reminder history",
            "payment reminder list", "kisko reminder bheja",
        ),
        companion_reads=("search_customer", "send_payment_reminder"),
    ),
    "merge_customers": ToolRetrievalMetadata(
        name="merge_customers",
        domain=ToolDomain.KHATA,
        action_type=ActionType.UPDATE,
        entity_type="customer",
        description="Stage merge of duplicate customer into primary (needs confirm). Both customer IDs required.",
        aliases=(
            "merge customer", "merge customers", "duplicate merge", "merge duplicate",
            "customer merge karo", "duplicate customer merge", "combine customers",
        ),
        companion_reads=("search_customer",),
    ),
    "payment_history": ToolRetrievalMetadata(
        name="payment_history",
        domain=ToolDomain.KHATA,
        action_type=ActionType.READ,
        entity_type="payment",
        description="Recent customer payments for this store. Not one customer's ledger.",
        aliases=(
            "payment history", "recent payments", "payments list", "store payments", "payment report",
            "collection history", "aaj ke payments", "customer payment history",
        ),
        companion_reads=("payment_mix", "customer_summary"),
    ),
    "payment_mix": ToolRetrievalMetadata(
        name="payment_mix",
        domain=ToolDomain.KHATA,
        action_type=ActionType.ANALYTICS,
        entity_type="payment",
        description="Deterministic breakdown of store payment collections by channel (cash, UPI, card, bank).",
        aliases=(
            "payment mix", "payment breakdown", "cash vs upi", "payment methods", "collection mode",
            "upi collection", "cash collection", "payment modes",
        ),
        companion_reads=("payment_history", "today_sale"),
    ),
    "record_customer_payment": ToolRetrievalMetadata(
        name="record_customer_payment",
        domain=ToolDomain.KHATA,
        action_type=ActionType.CREATE,
        entity_type="payment",
        description="Stage a structured customer payment (needs confirm). Use for formal settlements.",
        aliases=(
            "record customer payment", "formal payment", "structured payment", "invoice payment",
            "payment entry", "record payment", "upi payment record", "cash payment record",
        ),
        companion_reads=("search_customer", "payment_history"),
    ),
    "search_customer": ToolRetrievalMetadata(
        name="search_customer",
        domain=ToolDomain.KHATA,
        action_type=ActionType.SEARCH,
        entity_type="customer",
        description="Find a customer by name, phone, or email. Basic result is name, phone, email.",
        aliases=(
            "search customer", "find customer", "customer search", "customer details", "check customer",
            "grahak search", "party search", "customer phone", "customer email", "customer find",
        ),
        companion_reads=("customer_summary", "get_customer_ledger"),
    ),
    "send_payment_reminder": ToolRetrievalMetadata(
        name="send_payment_reminder",
        domain=ToolDomain.KHATA,
        action_type=ActionType.UPDATE,
        entity_type="payment",
        description="Stage a payment reminder to a customer (needs confirm). channel WhatsApp or SMS.",
        aliases=(
            "send payment reminder", "payment reminder", "send reminder", "reminder bhejo",
            "reminder send karo", "payment yaad dilao", "due reminder", "khata reminder",
        ),
        companion_reads=("search_customer", "list_payment_reminders"),
    ),
    "set_opening_balance": ToolRetrievalMetadata(
        name="set_opening_balance",
        domain=ToolDomain.KHATA,
        action_type=ActionType.UPDATE,
        entity_type="ledger",
        description="Stage opening khata balance for a customer who has no account yet (needs confirm).",
        aliases=(
            "set opening balance", "opening balance", "opening balance set", "khata opening",
            "opening khata", "shuruati balance", "opening due", "purana hisab set",
        ),
        companion_reads=("search_customer", "get_customer_ledger"),
    ),
    "top_customers": ToolRetrievalMetadata(
        name="top_customers",
        domain=ToolDomain.KHATA,
        action_type=ActionType.ANALYTICS,
        entity_type="customer",
        description="Customers who spent the most in up to 50 recent released bills.",
        aliases=(
            "top customers", "best customers", "high spending customers", "sabse jyada kharidari",
            "top buyers", "top grahak", "vip customers",
        ),
        companion_reads=("customer_summary", "today_sale"),
    ),
    "update_customer": ToolRetrievalMetadata(
        name="update_customer",
        domain=ToolDomain.KHATA,
        action_type=ActionType.UPDATE,
        entity_type="customer",
        description="Update customer by real ObjectId. Always send name + phone or email.",
        aliases=(
            "update customer", "edit customer", "customer update", "customer edit", "customer modify",
            "update phone", "update email", "phone badlo", "email badlo", "customer details update",
        ),
        companion_reads=("search_customer",),
    ),
    "update_customer_payment": ToolRetrievalMetadata(
        name="update_customer_payment",
        domain=ToolDomain.KHATA,
        action_type=ActionType.UPDATE,
        entity_type="payment",
        description="Stage update of payment notes only (needs confirm). Cannot change amount or mode.",
        aliases=(
            "update customer payment", "update payment note", "edit payment note", "payment notes edit",
            "payment note badlo", "payment remark update",
        ),
        companion_reads=("get_customer_payment", "payment_history"),
    ),

    # === FINANCE (6 tools) ===
    "cashbook_summary": ToolRetrievalMetadata(
        name="cashbook_summary",
        domain=ToolDomain.FINANCE,
        action_type=ActionType.READ,
        entity_type="cashbook",
        description="Daily and periodic cashbook summary: cash in/out, opening/closing balance.",
        aliases=(
            "cashbook summary", "cashbook", "galla", "counter cash", "cash in hand", "cash in cash out",
            "daily cash", "aaj ka galla", "cash balance", "cash report",
        ),
        companion_reads=("expense_summary", "today_sale"),
    ),
    "create_expense": ToolRetrievalMetadata(
        name="create_expense",
        domain=ToolDomain.FINANCE,
        action_type=ActionType.CREATE,
        entity_type="expense",
        description="Record a new expense for the store (e.g. rent, electricity, tea, staff salary).",
        aliases=(
            "create expense", "add expense", "record expense", "kharcha add", "add kharcha",
            "kharcha record", "kharcha dalo", "kharcha likho", "kharcha banao", "rent diya",
            "kiraya diya", "bill bhara", "light bill", "bijli bill", "chai nashta", "kharcha hua",
        ),
        companion_reads=("expense_summary", "list_expenses"),
    ),
    "expense_summary": ToolRetrievalMetadata(
        name="expense_summary",
        domain=ToolDomain.FINANCE,
        action_type=ActionType.READ,
        entity_type="expense",
        description="Store expense summary totals and category breakdown.",
        aliases=(
            "expense summary", "total expense", "total expenses", "kharcha summary", "total kharcha",
            "kitna kharcha hua", "kharcha report", "expense report", "category expense",
        ),
        companion_reads=("list_expenses", "cashbook_summary"),
    ),
    "gst_summary": ToolRetrievalMetadata(
        name="gst_summary",
        domain=ToolDomain.FINANCE,
        action_type=ActionType.READ,
        entity_type="gst",
        description="GST summary (taxable value, IGST, CGST, SGST, total tax) and B2B/B2C split.",
        aliases=(
            "gst summary", "gst report", "tax summary", "tax report", "cgst sgst", "gst return",
            "tax calculation", "input tax credit", "b2b gst",
        ),
        companion_reads=("today_sale", "invoice_summary"),
    ),
    "list_expenses": ToolRetrievalMetadata(
        name="list_expenses",
        domain=ToolDomain.FINANCE,
        action_type=ActionType.READ,
        entity_type="expense",
        description="List recent expenses with title, category, amount, payment method and status.",
        aliases=(
            "list expenses", "recent expenses", "expenses list", "kharcha list", "purane kharche",
            "kharcha dikhao", "view expenses", "all expenses",
        ),
        companion_reads=("expense_summary", "cashbook_summary"),
    ),
    "update_expense": ToolRetrievalMetadata(
        name="update_expense",
        domain=ToolDomain.FINANCE,
        action_type=ActionType.UPDATE,
        entity_type="expense",
        description="Update an existing expense by its expenseId (e.g. change payment status, category).",
        aliases=(
            "update expense", "edit expense", "expense update", "kharcha update", "mark expense paid",
            "expense overdue", "kharcha status badlo", "modify expense",
        ),
        companion_reads=("list_expenses", "expense_summary"),
    ),

    # === PROCUREMENT (5 tools) ===
    "bill_summary": ToolRetrievalMetadata(
        name="bill_summary",
        domain=ToolDomain.PROCUREMENT,
        action_type=ActionType.READ,
        entity_type="supplier",
        description="Supplier purchase bill analytics: total bills, paid bills, pending payable.",
        aliases=(
            "purchase bill summary", "supplier bills summary", "purchase bills", "supplier payable",
            "vendor bills", "purchase bill report", "vendor payment pending",
        ),
        companion_reads=("supplier_summary", "list_purchase_orders"),
    ),
    "create_purchase_order": ToolRetrievalMetadata(
        name="create_purchase_order",
        domain=ToolDomain.PROCUREMENT,
        action_type=ActionType.CREATE,
        entity_type="po",
        description="Draft a purchase order to order inventory from a supplier. Real supplierId required.",
        aliases=(
            "create purchase order", "draft purchase order", "new purchase order", "create po",
            "draft po", "po banao", "po create", "purchase order banao", "order from supplier",
            "supplier order", "supplier se order", "maal order", "stock order",
        ),
        companion_reads=("search_supplier", "search_product", "list_purchase_orders"),
    ),
    "list_purchase_orders": ToolRetrievalMetadata(
        name="list_purchase_orders",
        domain=ToolDomain.PROCUREMENT,
        action_type=ActionType.READ,
        entity_type="po",
        description="List purchase orders (PO) with PO number, supplier, status, total amount.",
        aliases=(
            "list purchase orders", "purchase orders list", "po list", "list po", "recent po",
            "supplier orders list", "purane po", "purchase orders dikhao",
        ),
        companion_reads=("search_supplier", "bill_summary"),
    ),
    "search_supplier": ToolRetrievalMetadata(
        name="search_supplier",
        domain=ToolDomain.PROCUREMENT,
        action_type=ActionType.SEARCH,
        entity_type="supplier",
        description="Search suppliers/vendors by name, company, phone, or GST number.",
        aliases=(
            "search supplier", "find supplier", "supplier search", "vendor search", "find vendor",
            "search vendor", "supplier phone", "supplier details", "dealer search",
        ),
        companion_reads=("supplier_summary", "list_purchase_orders"),
    ),
    "supplier_summary": ToolRetrievalMetadata(
        name="supplier_summary",
        domain=ToolDomain.PROCUREMENT,
        action_type=ActionType.READ,
        entity_type="supplier",
        description="Supplier analytics: total suppliers count and total payable/outstanding.",
        aliases=(
            "supplier summary", "vendor summary", "total suppliers", "supplier count",
            "supplier payable total", "vendor count", "total vendors",
        ),
        companion_reads=("search_supplier", "bill_summary"),
    ),

    # === GENERAL (3 tools) ===
    "list_staff": ToolRetrievalMetadata(
        name="list_staff",
        domain=ToolDomain.GENERAL,
        action_type=ActionType.READ,
        entity_type="staff",
        description="List store staff and team members with name, phone, role, and store assignment.",
        aliases=(
            "list staff", "staff list", "employees list", "store staff", "karamchari list",
            "staff members", "team members", "who works here", "staff details",
        ),
        companion_reads=("store_brief", "list_stores"),
    ),
    "list_stores": ToolRetrievalMetadata(
        name="list_stores",
        domain=ToolDomain.GENERAL,
        action_type=ActionType.READ,
        entity_type="store",
        description="List accessible stores with name, category, subCategories, and address.",
        aliases=(
            "list stores", "stores list", "all stores", "accessible stores", "meri dukane",
            "dukaan list", "all shops", "store list",
        ),
        companion_reads=("store_brief",),
    ),
    "store_brief": ToolRetrievalMetadata(
        name="store_brief",
        domain=ToolDomain.GENERAL,
        action_type=ActionType.READ,
        entity_type="store",
        description="Deterministic composite executive store brief: combines live sales, stock, and expenses.",
        aliases=(
            "store brief", "daily brief", "store summary", "store overview", "dukan ka hisab",
            "store ka hisab", "aaj ka pura hisab", "executive brief", "morning brief",
        ),
        companion_reads=("today_sale", "stock_summary", "expense_summary"),
    ),
}


ACTION_KEYWORDS: dict[ActionType, tuple[str, ...]] = {
    ActionType.CREATE: (
        "create", "add", "new", "draft", "make", "banao", "bana", "naya", "nayi", "jodo",
        "record", "dalo", "daal", "daalo", "stage", "register",
    ),
    ActionType.READ: (
        "get", "show", "list", "batao", "bata", "dikhao", "dikhana", "view", "report",
        "summary", "totals", "kitna", "kitne", "kitni", "history", "status", "overview",
    ),
    ActionType.UPDATE: (
        "update", "edit", "change", "modify", "badlo", "badal", "correct", "release",
        "mark", "merge", "send", "link",
    ),
    ActionType.DELETE: (
        "delete", "remove", "hatao", "hata", "cancel",
    ),
    ActionType.ANALYTICS: (
        "analytics", "analysis", "trend", "trends", "pareto", "velocity", "growth",
        "ratio", "breakdown",
    ),
    ActionType.SEARCH: (
        "search", "find", "dhundo", "lookup", "kisko",
    ),
}

ENTITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "customer": ("customer", "customers", "grahak", "party", "client", "buyer"),
    "product": ("product", "products", "item", "items", "saman", "saaman", "maal", "sku", "rate", "price"),
    "stock": ("stock", "inventory", "godown", "godam", "units", "quantity", "qty"),
    "invoice": ("invoice", "invoices", "bill", "bills", "challan", "parchi"),
    "order": ("order", "orders", "sales_order"),
    "po": ("po", "purchase_order", "purchase_orders"),
    "supplier": ("supplier", "suppliers", "vendor", "vendors", "dealer"),
    "expense": ("expense", "expenses", "kharch", "kharcha", "kharche", "kiraya", "rent", "electricity", "bijli"),
    "cashbook": ("cashbook", "cash", "galla", "counter"),
    "ledger": ("ledger", "khata", "hisab", "hisaab", "udhar", "udhaar", "due", "dues", "jama", "advance"),
    "payment": ("payment", "payments", "reminder", "reminders", "collect", "upi"),
    "staff": ("staff", "employee", "employees", "karamchari", "team"),
    "store": ("store", "stores", "dukan", "dukaan", "shop"),
    "gst": ("gst", "tax", "taxes", "cgst", "sgst", "igst"),
}

_STOPWORDS = frozenset({"his", "her", "the", "and", "for", "with", "test", "name", "email", "phone", "check"})


def damerau_levenshtein(s1: str, s2: str) -> int:
    d: dict[tuple[int, int], int] = {}
    len1 = len(s1)
    len2 = len(s2)
    for i in range(-1, len1 + 1):
        d[(i, -1)] = i + 1
    for j in range(-1, len2 + 1):
        d[(-1, j)] = j + 1

    for i in range(len1):
        for j in range(len2):
            cost = 0 if s1[i] == s2[j] else 1
            d[(i, j)] = min(
                d[(i - 1, j)] + 1,
                d[(i, j - 1)] + 1,
                d[(i - 1, j - 1)] + cost,
            )
            if i > 0 and j > 0 and s1[i] == s2[j - 1] and s1[i - 1] == s2[j]:
                d[(i, j)] = min(d[(i, j)], d[(i - 2, j - 2)] + 1)

    return d[(len1 - 1, len2 - 1)]


def normalize_query_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    lowered = decomposed.lower()
    cleaned = re.sub(r"[\s\-_.,:;!?\'\"/\\()\[\]{}]+", " ", lowered)
    return cleaned.strip()


def extract_normalized_tokens(text: str) -> list[str]:
    norm = normalize_query_text(text)
    return [tok for tok in norm.split() if len(tok) >= 2]


@dataclass
class HybridScoringResult:
    tool_name: str
    score: float
    matched_action: ActionType | None = None
    matched_entity: str | None = None
    alias_match: bool = False


class HybridToolRetriever:
    def __init__(self, catalog: dict[str, ToolRetrievalMetadata] | None = None) -> None:
        self._catalog = catalog or TOOL_METADATA_CATALOG

    def _match_token_action(self, token: str) -> tuple[ActionType, float] | None:
        if len(token) < 3 or token in _STOPWORDS:
            return None
        best_act: ActionType | None = None
        best_sim = 0.0
        for act, words in ACTION_KEYWORDS.items():
            for w in words:
                if token == w:
                    return (act, 1.0)
                if abs(len(token) - len(w)) <= 2:
                    dist = damerau_levenshtein(token, w)
                    max_l = max(len(token), len(w))
                    sim = 1.0 - (dist / max_l)
                    if (max_l <= 4 and dist <= 1 and sim >= 0.75) or (max_l > 4 and dist <= 2 and sim >= 0.75):
                        if sim > best_sim:
                            best_sim = sim
                            best_act = act
        return (best_act, best_sim) if best_act else None

    def _match_token_entity(self, token: str) -> tuple[str, float] | None:
        if len(token) < 3 or token in _STOPWORDS:
            return None
        best_ent: str | None = None
        best_sim = 0.0
        for ent, words in ENTITY_KEYWORDS.items():
            for w in words:
                if token == w:
                    return (ent, 1.0)
                if abs(len(token) - len(w)) <= 2:
                    dist = damerau_levenshtein(token, w)
                    max_l = max(len(token), len(w))
                    sim = 1.0 - (dist / max_l)
                    if (max_l <= 4 and dist <= 1 and sim >= 0.75) or (max_l > 4 and dist <= 2 and sim >= 0.75):
                        if sim > best_sim:
                            best_sim = sim
                            best_ent = ent
        return (best_ent, best_sim) if best_ent else None

    def retrieve_candidates(
        self,
        query: str,
        *,
        available_tools: Iterable[str],
        limit: int = 8,
    ) -> list[HybridScoringResult]:
        available_set = frozenset(available_tools)
        tokens = extract_normalized_tokens(query)
        normalized_q = normalize_query_text(query)

        detected_actions: dict[ActionType, float] = {}
        detected_entities: dict[str, float] = {}

        for tok in tokens:
            m_act = self._match_token_action(tok)
            if m_act:
                act, sim = m_act
                detected_actions[act] = max(detected_actions.get(act, 0.0), sim)

            m_ent = self._match_token_entity(tok)
            if m_ent:
                ent, sim = m_ent
                detected_entities[ent] = max(detected_entities.get(ent, 0.0), sim)

        scores: list[HybridScoringResult] = []

        for name, meta in self._catalog.items():
            if name not in available_set:
                continue

            tool_score = 0.0
            alias_matched = False

            for alias in meta.aliases:
                norm_alias = normalize_query_text(alias)
                if norm_alias in normalized_q:
                    alias_matched = True
                    tool_score += 15.0
                    break
                alias_words = norm_alias.split()
                if len(alias_words) > 1 and all(w in tokens for w in alias_words):
                    alias_matched = True
                    tool_score += 12.0
                    break

            entity_weight = detected_entities.get(meta.entity_type, 0.0)
            if entity_weight > 0.0:
                tool_score += entity_weight * 10.0

            action_weight = detected_actions.get(meta.action_type, 0.0)
            if action_weight > 0.0:
                tool_score += action_weight * 8.0

            if name in normalized_q or name.replace("_", " ") in normalized_q:
                tool_score += 20.0

            if entity_weight > 0.0 and action_weight > 0.0:
                tool_score += 10.0

            if tool_score > 0.0:
                scores.append(
                    HybridScoringResult(
                        tool_name=name,
                        score=tool_score,
                        matched_action=meta.action_type if action_weight > 0.0 else None,
                        matched_entity=meta.entity_type if entity_weight > 0.0 else None,
                        alias_match=alias_matched,
                    )
                )

        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[:limit]


GLOBAL_TOOL_RETRIEVER = HybridToolRetriever()
