from app.schemas.tool import ToolDefinition, ToolDomain, ToolRisk

_STORE_ID_PROP = {
    "type": "string",
    "pattern": "^[a-fA-F0-9]{24}$",
    "description": "Active store ObjectId",
}

_OBJECT_ID_PROP = {
    "type": "string",
    "pattern": "^[a-fA-F0-9]{24}$",
}

_PHONE_PROP = {
    "type": "string",
    "pattern": "^[6-9]\\d{9}$",
    "description": "Indian 10-digit mobile number (required if email omitted)",
}

_RAW_READ_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="search_product",
        description="Search live products by name/SKU (price, stock, status).",
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Product search text",
                },
            },
            "required": ["storeId", "query"],
        },
    ),
    ToolDefinition(
        name="today_sale",
        description="Today's live sales: revenue, profit, bill count.",
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="stock_summary",
        description=(
            "Inventory/stock totals only (qty on hand, low/out of stock). "
            "Not the count of listed products — use product_summary for "
            "how many products are created/listed."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="product_summary",
        description=(
            "How many products are listed/created in the catalog "
            "(total, active, inactive) — includes products with zero "
            "stock. Use for 'total products' / 'kitne product listed'."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="search_customer",
        description=(
            "Find a customer by name, phone, or email. Basic result is "
            "name, phone, email, and active status. Address, GST, khata "
            "totals, and ledger lines are added only when the user asked "
            "for that part."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Customer name, phone, or email search text",
                },
            },
            "required": ["storeId", "query"],
        },
    ),
    ToolDefinition(
        name="customer_dossier",
        description=(
            "Who someone is: one customer match plus their saved memo, "
            "dues if present, and up to 10 recent bills. Not a biography."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Customer name, phone, or email search text",
                },
            },
            "required": ["storeId", "query"],
        },
    ),
    ToolDefinition(
        name="top_customers",
        description=(
            "Customers who spent the most, summed from recent released "
            "bills. Not all-time if the store has more than 500 bills."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "How many customers to return",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="payment_history",
        description=(
            "Recent customer payments for this store. Not one customer's ledger lines."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="list_stores",
        description=(
            "List accessible stores with name, category, subCategories, "
            "and which is active. Use for store name, category, count, "
            "or which products/categories fit THIS store — never guess "
            "category from the store name alone."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="customer_summary",
        description=(
            "Store customer totals: total customers, today new, and new "
            "customers in last 7/15/30 days (and longer windows). Set "
            "periodDays for detailed period analytics (growth, averages)."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "periodDays": {
                    "type": "integer",
                    "enum": [7, 15, 30],
                    "description": (
                        "Optional lookback for detailed customer analytics. "
                        "Omit for all-time totals + new-customer windows."
                    ),
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="get_customer_ledger",
        description=(
            "Standalone khata ledger lines for one customer (running "
            "balance, type, amount). Prefer this over search_customer "
            "ledger slice when the user asks for ledger history."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Customer ObjectId",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Max ledger lines (default 50)",
                },
            },
            "required": ["storeId", "customerId"],
        },
    ),
    ToolDefinition(
        name="list_customer_accounts",
        description=(
            "List customer khata accounts (dues/advance). Use hasDue=true "
            "for customers with outstanding balance."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Optional filter to one customer",
                },
                "hasDue": {
                    "type": "boolean",
                    "description": "If true, only accounts with dues",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Max accounts (default 20)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="get_customer_payment",
        description="Fetch one customer payment by payment ObjectId.",
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "paymentId": {
                    **_OBJECT_ID_PROP,
                    "description": "Payment ObjectId",
                },
            },
            "required": ["storeId", "paymentId"],
        },
    ),
    ToolDefinition(
        name="list_payment_reminders",
        description=(
            "List payment reminders sent for this store (optional customerId filter)."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Optional customer filter",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="invoice_summary",
        description=(
            "Invoice/bill counts and amounts. Returns all-time totals, "
            "today's invoices, and optionally a period window "
            "(periodDays=7/15/30) for last N days invoice count/revenue."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "periodDays": {
                    "type": "integer",
                    "enum": [1, 7, 15, 30],
                    "description": (
                        "Optional lookback window in days. Use 7 for "
                        "last week, 30 for last month. Omit for "
                        "all-time + today only."
                    ),
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="stock_items",
        description=(
            "Itemized inventory stock rows across products and variants "
            "(name, SKU, stock quantity, stock status, purchase & selling prices). "
            "Capped at 30 items."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "includeServices": {
                    "type": "boolean",
                    "description": "Include service items without physical stock",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="list_invoices",
        description=(
            "List recent invoices/bills with status, customer, date, and grand total. "
            "Capped at 30 invoices."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Optional customer ObjectId filter",
                },
                "invoiceStatus": {
                    "type": "string",
                    "enum": ["RELEASED", "DRAFT", "CANCELLED"],
                    "description": "Filter by status (default RELEASED)",
                },
                "paymentStatus": {
                    "type": "string",
                    "enum": ["PAID", "PARTIALLY_PAID", "UNPAID"],
                    "description": "Filter by payment status",
                },
                "startDate": {
                    "type": "string",
                    "description": "Start date filter (YYYY-MM-DD)",
                },
                "endDate": {
                    "type": "string",
                    "description": "End date filter (YYYY-MM-DD)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Max invoices to return (default 20, max 30)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="expense_summary",
        description="Store expense summary totals and category breakdown.",
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="list_expenses",
        description=(
            "List recent expenses with title, category, amount, payment mode, "
            "and date. Capped at 20."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "category": {
                    "type": "string",
                    "maxLength": 100,
                    "description": "Filter by expense category",
                },
                "startDate": {
                    "type": "string",
                    "description": "Start date filter (YYYY-MM-DD)",
                },
                "endDate": {
                    "type": "string",
                    "description": "End date filter (YYYY-MM-DD)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max expenses (default 20)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="cashbook_summary",
        description=(
            "Daily and periodic cashbook summary: cash in/out, opening/closing "
            "balance, and day status."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "fromDate": {
                    "type": "string",
                    "description": "From date (YYYY-MM-DD)",
                },
                "toDate": {
                    "type": "string",
                    "description": "To date (YYYY-MM-DD)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="search_supplier",
        description="Search suppliers/vendors by name, company, phone, or GST number.",
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "query": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "Supplier name, phone, or company search text",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max suppliers (default 10)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="supplier_summary",
        description=(
            "Supplier analytics: total suppliers count and total payable/due amounts."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="list_purchase_orders",
        description=(
            "List purchase orders (PO) with PO number, supplier, status, date, "
            "and amount. Capped at 20."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "status": {
                    "type": "string",
                    "description": (
                        "PO status filter (e.g. DRAFT, PENDING, APPROVED, "
                        "RECEIVED, CANCELLED)"
                    ),
                },
                "supplierId": {
                    **_OBJECT_ID_PROP,
                    "description": "Optional supplier ObjectId filter",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max purchase orders (default 20)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="bill_summary",
        description=(
            "Supplier purchase bill analytics: total bills, paid bills, "
            "pending/overdue bills, and payable/paid/due amounts."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="gst_summary",
        description=(
            "GST summary (taxable value, IGST, CGST, SGST, total tax) and "
            "GST compliance health score."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "month": {
                    "type": "string",
                    "description": "Month number (1-12) or name",
                },
                "quarter": {
                    "type": "string",
                    "description": "Quarter (Q1, Q2, Q3, Q4)",
                },
                "year": {
                    "type": "string",
                    "description": "Financial/calendar year (e.g. 2025)",
                },
                "period": {
                    "type": "string",
                    "description": "Period identifier (e.g. 2025-03, Q4-2025)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="list_sales_orders",
        description=(
            "List customer sales orders with order number, customer, status, "
            "payment status, and total amount. Capped at 20."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "status": {
                    "type": "string",
                    "description": (
                        "Order status (PENDING, CONFIRMED, SHIPPED, "
                        "DELIVERED, CANCELLED)"
                    ),
                },
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Optional customer ObjectId filter",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Max orders (default 20)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="list_staff",
        description=(
            "List store staff and team members with name, phone, role, "
            "and active status."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="customer_detailed_analytics",
        description=(
            "Detailed periodic customer analytics (growth, acquisition, order "
            "frequency) over 7, 15, or 30 days."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "periodDays": {
                    "type": "integer",
                    "enum": [7, 15, 30],
                    "description": "Lookback period in days (7, 15, 30)",
                },
                "analyticsType": {
                    "type": "string",
                    "enum": ["overview", "growth", "cohort"],
                    "description": "Analytics slice (default overview)",
                },
            },
            "required": ["storeId", "periodDays"],
        },
    ),
    ToolDefinition(
        name="invoice_detailed_analytics",
        description=(
            "Detailed periodic invoice/sales analytics (revenue trend, profit, "
            "sales volume) over 1, 7, 15, or 30 days."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "periodDays": {
                    "type": "integer",
                    "enum": [1, 7, 15, 30],
                    "description": "Lookback period in days (1, 7, 15, 30)",
                },
            },
            "required": ["storeId", "periodDays"],
        },
    ),
    ToolDefinition(
        name="sales_pareto",
        description=(
            "Deterministic 80/20 Pareto product sales analysis: calculates "
            "top revenue-generating products, units sold, and cumulative revenue "
            "shares from verified invoices over a time window (today, 7d, 30d)."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "window": {
                    "type": "string",
                    "enum": ["today", "7d", "30d", "90d"],
                    "description": "Analysis window (default '7d')",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum top products to return (default 20)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="payment_mix",
        description=(
            "Deterministic breakdown of store payment collections by channel "
            "(Cash, UPI, Card, Credit/Udhaar, Bank Transfer) over a time window "
            "(today, 7d, 30d)."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "window": {
                    "type": "string",
                    "enum": ["today", "7d", "30d", "90d"],
                    "description": "Analysis window (default '7d')",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="inventory_velocity",
        description=(
            "Deterministic inventory sales velocity and scanning: correlates catalog "
            "stock against observed sales to identify fast-moving products and items "
            "with zero sales observed in the scanned window."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "window": {
                    "type": "string",
                    "enum": ["today", "7d", "30d", "90d"],
                    "description": "Analysis window (default '7d')",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum items per category (default 20)",
                },
            },
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="store_brief",
        description=(
            "Deterministic composite executive store brief: combines live sales "
            "today, inventory stock alerts, customer receivables/dues, and "
            "expenses into a single verified report."
        ),
        risk=ToolRisk.READ,
        allows_parallel=True,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "date": {
                    "type": "string",
                    "description": (
                        "Optional date in YYYY-MM-DD format (defaults to today)"
                    ),
                },
            },
            "required": ["storeId"],
        },
    ),
)

_ADDRESS_FIELDS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {"type": "string", "maxLength": 100},
        "addressLine1": {"type": "string", "maxLength": 300},
        "city": {"type": "string", "maxLength": 100},
        "stateCode": {
            "type": "string",
            "maxLength": 10,
            "description": "Indian state code (e.g. MH, DL)",
        },
        "pincode": {"type": "string", "maxLength": 10},
    },
}

_COMPANY_DETAILS_FIELDS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "gstin": {
            "type": "string",
            "minLength": 15,
            "maxLength": 15,
            "description": "15-char GSTIN",
        },
        "companyName": {"type": "string", "maxLength": 200},
        "gstDetail": {
            "type": "string",
            "maxLength": 500,
            "description": "Required when gstin is set",
        },
    },
}

_RAW_WRITE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="create_customer",
        description=(
            "Create customer (name + either phone or email from user). "
            "Never invent name/phone/email/ids."
        ),
        risk=ToolRisk.WRITE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "name": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 100,
                },
                "phone": _PHONE_PROP,
                "email": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 200,
                    "description": "Customer email (required if phone omitted)",
                },
            },
            "required": ["storeId", "name"],
        },
    ),
    ToolDefinition(
        name="update_customer",
        description=(
            "Update customer by real ObjectId. Always send name + phone "
            "or email (Core requires them). Optional: note, "
            "companyDetails (GST), addresses (billing/shipping). "
            "Resolve via search_customer first. Not for delete/bulk."
        ),
        risk=ToolRisk.WRITE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Existing customer ObjectId",
                },
                "name": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 100,
                },
                "phone": _PHONE_PROP,
                "email": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 200,
                    "description": "Customer email (required if phone omitted)",
                },
                "note": {
                    "type": "string",
                    "maxLength": 1000,
                    "description": "Freeform customer note",
                },
                "companyDetails": _COMPANY_DETAILS_FIELDS,
                "addresses": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "billing": _ADDRESS_FIELDS,
                        "shipping": _ADDRESS_FIELDS,
                    },
                },
            },
            "required": ["storeId", "customerId", "name"],
        },
    ),
    ToolDefinition(
        name="create_invoice_draft",
        description=(
            "Create DRAFT invoice only (no stock deduct). Items need real "
            "product ObjectIds + qty>=1; optional customerId (else walk-in)."
        ),
        risk=ToolRisk.WRITE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Optional customer ObjectId",
                },
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "product": {
                                **_OBJECT_ID_PROP,
                                "description": "Product ObjectId from search",
                            },
                            "quantity": {
                                "type": "number",
                                "minimum": 1,
                            },
                        },
                        "required": ["product", "quantity"],
                    },
                },
            },
            "required": ["storeId", "items"],
        },
    ),
    ToolDefinition(
        name="update_invoice_draft",
        description=(
            "Update existing DRAFT: link customer and/or replace items. "
            "Prefer this over a second draft for the same bill."
        ),
        risk=ToolRisk.WRITE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "invoiceId": {
                    **_OBJECT_ID_PROP,
                    "description": "Existing DRAFT invoice ObjectId",
                },
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Real customer ObjectId to link",
                },
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "product": {
                                **_OBJECT_ID_PROP,
                                "description": "Product ObjectId from search",
                            },
                            "quantity": {
                                "type": "number",
                                "minimum": 1,
                            },
                        },
                        "required": ["product", "quantity"],
                    },
                },
            },
            "required": ["storeId", "invoiceId"],
        },
    ),
    ToolDefinition(
        name="update_expense",
        description=(
            "Update an existing expense by its expenseId (e.g. change payment status "
            "to 'OVERDUE', 'PAID', 'PENDING', or 'CANCELLED', update amount, title, "
            "category, date, or description/note). Only provide fields to update."
        ),
        risk=ToolRisk.WRITE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "expenseId": {
                    **_OBJECT_ID_PROP,
                    "description": (
                        "Existing expense ObjectId from prior context or search"
                    ),
                },
                "title": {
                    "type": "string",
                    "description": "Optional updated title/name of expense",
                },
                "amount": {
                    "type": "number",
                    "minimum": 0.01,
                    "description": "Optional updated expense amount in INR (> 0)",
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Optional updated expense category: 'daily-expenses', "
                        "'rent', 'transport', 'staff-wages', 'utilities', "
                        "'shop-supplies', 'office-supplies', 'maintenance', "
                        "'marketing', or 'miscellaneous'"
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Optional updated ISO date (YYYY-MM-DD)",
                },
                "paymentMode": {
                    "type": "string",
                    "description": (
                        "Optional updated payment mode: 'CASH', 'UPI', "
                        "'BANK_TRANSFER', 'CARD', 'OTHER'"
                    ),
                },
                "description": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Optional updated description or note",
                },
                "status": {
                    "type": "string",
                    "enum": ["PAID", "PENDING", "OVERDUE", "CANCELLED"],
                    "description": (
                        "Payment status to set: 'PAID', 'PENDING', 'OVERDUE', "
                        "or 'CANCELLED'"
                    ),
                },
            },
            "required": ["storeId", "expenseId"],
        },
    ),
)

_LEDGER_PARAMETERS = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "storeId": _STORE_ID_PROP,
        "customerId": {
            **_OBJECT_ID_PROP,
            "description": "Customer ObjectId",
        },
        "amount": {
            "type": "number",
            "minimum": 0.01,
            "description": "Amount in INR",
        },
        "notes": {
            "type": "string",
            "maxLength": 500,
        },
    },
    "required": ["storeId", "customerId", "amount"],
}

_RAW_SENSITIVE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="release_invoice",
        description=(
            "Stage DRAFT release (stock deduct); needs user confirm. "
            "Real draft invoice ObjectId only."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "invoiceId": {
                    **_OBJECT_ID_PROP,
                    "description": "Draft invoice ObjectId to release",
                },
            },
            "required": ["storeId", "invoiceId"],
        },
    ),
    ToolDefinition(
        name="ledger_credit",
        description=(
            "Stage customer PAYMENT (khata credit) for user confirm. "
            "Real customerId and amount. Does not post until confirmed."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters=_LEDGER_PARAMETERS,
    ),
    ToolDefinition(
        name="ledger_debit",
        description=(
            "Stage customer DEBIT on khata (increases due) for user confirm. "
            "Real customerId and amount. Does not post until confirmed."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters=_LEDGER_PARAMETERS,
    ),
    ToolDefinition(
        name="add_stock",
        description=(
            "Stage stock-in for one or more products (needs user confirm). "
            "Resolve each productId via search_product first. Supports "
            "multi-line intake (product A from person X, product B from "
            "person Y) in one call via items[]. Optional sourceName is "
            "the person/supplier name for display only. Does not post "
            "until confirmed. Preview shows currentStock, adding, "
            "finalStock per line."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "productId": {
                                **_OBJECT_ID_PROP,
                                "description": "Product ObjectId from search",
                            },
                            "quantity": {
                                "type": "number",
                                "minimum": 0.01,
                                "description": "Units to add",
                            },
                            "productName": {
                                "type": "string",
                                "maxLength": 200,
                                "description": "Display name from search",
                            },
                            "sourceName": {
                                "type": "string",
                                "maxLength": 120,
                                "description": (
                                    "Who stock came from (person/supplier "
                                    "name). Display only — not a supplier id."
                                ),
                            },
                            "currentStock": {
                                "type": "number",
                                "minimum": 0,
                                "description": (
                                    "Current available qty from "
                                    "search_product.stock if known"
                                ),
                            },
                            "purchasePrice": {
                                "type": "number",
                                "minimum": 0.01,
                                "description": (
                                    "Cost per unit. Use product cost/"
                                    "sellingPrice when user did not give one."
                                ),
                            },
                        },
                        "required": ["productId", "quantity"],
                    },
                },
            },
            "required": ["storeId", "items"],
        },
    ),
    ToolDefinition(
        name="merge_customers",
        description=(
            "Stage merge of duplicate customer into primary (needs "
            "confirm). Pass real primaryId + duplicateId from "
            "search_customer. Duplicate is soft-deactivated."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "primaryId": {
                    **_OBJECT_ID_PROP,
                    "description": "Customer to keep",
                },
                "duplicateId": {
                    **_OBJECT_ID_PROP,
                    "description": "Duplicate to merge away",
                },
            },
            "required": ["storeId", "primaryId", "duplicateId"],
        },
    ),
    ToolDefinition(
        name="set_opening_balance",
        description=(
            "Stage opening khata balance for a customer who has no "
            "account yet (needs confirm). Never use for file import "
            "or bulk. Pass customerId + totalDue and/or totalPaid."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Customer ObjectId",
                },
                "totalDue": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Opening due amount INR",
                },
                "totalPaid": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Opening paid/advance INR",
                },
                "totalAmount": {
                    "type": "number",
                    "minimum": 0,
                },
                "notes": {"type": "string", "maxLength": 500},
            },
            "required": ["storeId", "customerId"],
        },
    ),
    ToolDefinition(
        name="record_customer_payment",
        description=(
            "Stage a structured customer payment (needs confirm). Use "
            "for formal payment entries with method/type. For quick "
            "khata jama prefer ledger_credit. paymentType: "
            "LEDGER_PAYMENT | INVOICE_PAYMENT | ADJUSTMENT | REFUND."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Customer ObjectId",
                },
                "paymentType": {
                    "type": "string",
                    "enum": [
                        "LEDGER_PAYMENT",
                        "INVOICE_PAYMENT",
                        "ADJUSTMENT",
                        "REFUND",
                    ],
                },
                "payment": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "method": {
                                "type": "string",
                                "enum": [
                                    "CASH",
                                    "UPI",
                                    "BANK_TRANSFER",
                                    "CHEQUE",
                                    "CREDIT",
                                ],
                            },
                            "amount": {
                                "type": "number",
                                "minimum": 0.01,
                            },
                        },
                        "required": ["method", "amount"],
                    },
                },
                "invoiceId": {
                    **_OBJECT_ID_PROP,
                    "description": "Required for INVOICE_PAYMENT if no allocations",
                },
                "invoiceAllocations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "invoice": _OBJECT_ID_PROP,
                            "amount": {
                                "type": "number",
                                "minimum": 0.01,
                            },
                        },
                        "required": ["invoice", "amount"],
                    },
                },
                "notes": {"type": "string", "maxLength": 500},
            },
            "required": [
                "storeId",
                "customerId",
                "paymentType",
                "payment",
            ],
        },
    ),
    ToolDefinition(
        name="update_customer_payment",
        description=(
            "Stage update of payment notes only (needs confirm). "
            "Cannot change amount/method."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "paymentId": {
                    **_OBJECT_ID_PROP,
                    "description": "Payment ObjectId",
                },
                "notes": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Updated notes",
                },
            },
            "required": ["storeId", "paymentId", "notes"],
        },
    ),
    ToolDefinition(
        name="create_collect_link",
        description=(
            "Stage a payment collect link for a customer (needs "
            "confirm). Optional amount; omit to collect full due."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Customer ObjectId",
                },
                "amount": {
                    "type": "number",
                    "minimum": 0.01,
                    "description": "Collect amount INR (optional)",
                },
                "notes": {"type": "string", "maxLength": 500},
                "description": {"type": "string", "maxLength": 500},
            },
            "required": ["storeId", "customerId"],
        },
    ),
    ToolDefinition(
        name="send_payment_reminder",
        description=(
            "Stage a payment reminder to a customer (needs confirm). "
            "channel defaults to EMAIL (SMS/WHATSAPP may be unavailable)."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "customerId": {
                    **_OBJECT_ID_PROP,
                    "description": "Customer ObjectId",
                },
                "channel": {
                    "type": "string",
                    "enum": ["EMAIL", "SMS", "WHATSAPP"],
                    "description": "Delivery channel (default EMAIL)",
                },
                "includePaymentLink": {
                    "type": "boolean",
                    "description": "Include collect link (default true)",
                },
                "notes": {"type": "string", "maxLength": 500},
            },
            "required": ["storeId", "customerId"],
        },
    ),
    ToolDefinition(
        name="create_expense",
        description=(
            "Record a new expense for the store (e.g. rent, electricity, "
            "tea/refreshments, salaries, maintenance, delivery, supplies). "
            "Requires user confirmation before execution."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "title": {
                    "type": "string",
                    "description": (
                        "Short description of expense (e.g. 'Store Rent', "
                        "'Electricity bill', 'Chai nashta')"
                    ),
                },
                "amount": {
                    "type": "number",
                    "minimum": 0.01,
                    "description": "Expense amount in INR (> 0)",
                },
                "category": {
                    "type": "string",
                    "description": (
                        "Expense category value. Valid values: "
                        "'daily-expenses' (Tea & Snacks / Chai / nashta / food), "
                        "'rent' (Rent / Kiraya), 'transport' (Delivery / Transport / "
                        "Fuel / Dhulai), 'staff-wages' (Salary / Wages / Pagar), "
                        "'utilities' (Electricity / Water / Bijli), "
                        "'shop-supplies' (Bags / Packaging), 'office-supplies' "
                        "(Stationery), 'maintenance' (Repairs), 'marketing', "
                        "'miscellaneous'"
                    ),
                },
                "date": {
                    "type": "string",
                    "description": "Optional ISO date (YYYY-MM-DD)",
                },
                "paymentMode": {
                    "type": "string",
                    "description": (
                        "Optional payment mode: 'CASH', 'UPI', "
                        "'BANK_TRANSFER', 'CARD', 'OTHER'"
                    ),
                },
                "description": {
                    "type": "string",
                    "maxLength": 500,
                    "description": (
                        "Optional professional description or note for the "
                        "expense (e.g. 'Electricity bill for September 2026'). "
                        "Intelligently formulate from user context."
                    ),
                },
                "status": {
                    "type": "string",
                    "enum": ["PAID", "PENDING", "OVERDUE", "CANCELLED"],
                    "description": (
                        "Optional payment status: 'PAID' (already paid / "
                        "cleared, e.g. 'bill bhra'), 'PENDING' (yet to pay), "
                        "or 'OVERDUE'. Default is 'PAID' if paid, else 'PENDING'."
                    ),
                },
            },
            "required": ["storeId", "title", "amount", "category"],
        },
    ),
    ToolDefinition(
        name="create_purchase_order",
        description=(
            "Draft a purchase order to order inventory from a supplier. "
            "Requires supplierId, items with productId and quantity. "
            "Requires user confirmation before execution."
        ),
        risk=ToolRisk.SENSITIVE,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "storeId": _STORE_ID_PROP,
                "supplierId": {
                    **_OBJECT_ID_PROP,
                    "description": "Supplier ObjectId (from search_supplier)",
                },
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "productId": {
                                **_OBJECT_ID_PROP,
                                "description": "Product ObjectId (from search_product)",
                            },
                            "quantity": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Quantity to order",
                            },
                            "productName": {
                                "type": "string",
                                "maxLength": 200,
                                "description": "Display name of product",
                            },
                        },
                        "required": ["productId", "quantity"],
                    },
                },
                "supplierName": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "Display name of supplier",
                },
                "paymentTerms": {
                    "type": "string",
                    "description": "Payment terms (e.g. '30_DAYS', 'IMMEDIATE')",
                },
                "reference": {
                    "type": "string",
                    "maxLength": 100,
                    "description": "Optional reference or memo",
                },
                "notes": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Optional notes or instructions",
                },
                "expectedDeliveryDate": {
                    "type": "string",
                    "description": "Optional expected delivery date (YYYY-MM-DD)",
                },
            },
            "required": ["storeId", "supplierId", "items"],
        },
    ),
)


TOOL_DOMAINS: dict[str, ToolDomain] = {
    # Inventory
    "search_product": ToolDomain.INVENTORY,
    "stock_summary": ToolDomain.INVENTORY,
    "product_summary": ToolDomain.INVENTORY,
    "stock_items": ToolDomain.INVENTORY,
    "inventory_velocity": ToolDomain.INVENTORY,
    "add_stock": ToolDomain.INVENTORY,
    # Procurement
    "search_supplier": ToolDomain.PROCUREMENT,
    "supplier_summary": ToolDomain.PROCUREMENT,
    "list_purchase_orders": ToolDomain.PROCUREMENT,
    "bill_summary": ToolDomain.PROCUREMENT,
    "create_purchase_order": ToolDomain.PROCUREMENT,
    # Sales
    "today_sale": ToolDomain.SALES,
    "invoice_summary": ToolDomain.SALES,
    "list_invoices": ToolDomain.SALES,
    "list_sales_orders": ToolDomain.SALES,
    "invoice_detailed_analytics": ToolDomain.SALES,
    "sales_pareto": ToolDomain.SALES,
    "create_invoice_draft": ToolDomain.SALES,
    "update_invoice_draft": ToolDomain.SALES,
    "release_invoice": ToolDomain.SALES,
    # Khata
    "search_customer": ToolDomain.KHATA,
    "customer_dossier": ToolDomain.KHATA,
    "top_customers": ToolDomain.KHATA,
    "payment_history": ToolDomain.KHATA,
    "customer_summary": ToolDomain.KHATA,
    "get_customer_ledger": ToolDomain.KHATA,
    "list_customer_accounts": ToolDomain.KHATA,
    "get_customer_payment": ToolDomain.KHATA,
    "list_payment_reminders": ToolDomain.KHATA,
    "customer_detailed_analytics": ToolDomain.KHATA,
    "payment_mix": ToolDomain.KHATA,
    "create_customer": ToolDomain.KHATA,
    "update_customer": ToolDomain.KHATA,
    "merge_customers": ToolDomain.KHATA,
    "set_opening_balance": ToolDomain.KHATA,
    "ledger_credit": ToolDomain.KHATA,
    "ledger_debit": ToolDomain.KHATA,
    "record_customer_payment": ToolDomain.KHATA,
    "update_customer_payment": ToolDomain.KHATA,
    "create_collect_link": ToolDomain.KHATA,
    "send_payment_reminder": ToolDomain.KHATA,
    # Finance
    "expense_summary": ToolDomain.FINANCE,
    "list_expenses": ToolDomain.FINANCE,
    "cashbook_summary": ToolDomain.FINANCE,
    "gst_summary": ToolDomain.FINANCE,
    "create_expense": ToolDomain.FINANCE,
    "update_expense": ToolDomain.FINANCE,
    # General / Overview
    "list_stores": ToolDomain.GENERAL,
    "list_staff": ToolDomain.GENERAL,
    "store_brief": ToolDomain.GENERAL,
}

TOOL_PERMISSIONS: dict[str, tuple[str, ...]] = {
    # Inventory
    "search_product": ("inventory:read",),
    "stock_summary": ("inventory:read",),
    "product_summary": ("inventory:read",),
    "stock_items": ("inventory:read",),
    "inventory_velocity": ("inventory:read",),
    "add_stock": ("inventory:write",),
    # Procurement
    "search_supplier": ("suppliers:read",),
    "supplier_summary": ("suppliers:read",),
    "list_purchase_orders": ("purchase_orders:read",),
    "bill_summary": ("bills:read",),
    "create_purchase_order": ("purchase_orders:write",),
    # Sales
    "today_sale": ("sales:read",),
    "invoice_summary": ("invoices:read",),
    "list_invoices": ("invoices:read",),
    "list_sales_orders": ("sales:read",),
    "invoice_detailed_analytics": ("invoices:read",),
    "sales_pareto": ("sales:read",),
    "create_invoice_draft": ("invoices:write",),
    "update_invoice_draft": ("invoices:write",),
    "release_invoice": ("invoices:write",),
    # Khata
    "search_customer": ("customers:read",),
    "customer_dossier": ("customers:read",),
    "top_customers": ("customers:read",),
    "payment_history": ("payments:read",),
    "customer_summary": ("customers:read",),
    "get_customer_ledger": ("ledger:read",),
    "list_customer_accounts": ("customers:read",),
    "get_customer_payment": ("payments:read",),
    "list_payment_reminders": ("reminders:read",),
    "customer_detailed_analytics": ("customers:read",),
    "payment_mix": ("payments:read",),
    "create_customer": ("customers:write",),
    "update_customer": ("customers:write",),
    "merge_customers": ("customers:write",),
    "set_opening_balance": ("ledger:write",),
    "ledger_credit": ("ledger:write",),
    "ledger_debit": ("ledger:write",),
    "record_customer_payment": ("payments:write",),
    "update_customer_payment": ("payments:write",),
    "create_collect_link": ("payments:write",),
    "send_payment_reminder": ("reminders:write",),
    # Finance
    "expense_summary": ("expenses:read",),
    "list_expenses": ("expenses:read",),
    "cashbook_summary": ("cashbook:read",),
    "gst_summary": ("gst:read",),
    "create_expense": ("expenses:write",),
    "update_expense": ("expenses:write",),
    # General / Overview
    "list_stores": ("stores:read",),
    "list_staff": ("staff:read",),
    "store_brief": ("stores:read",),
}


def _enrich_definition(defn: ToolDefinition) -> ToolDefinition:
    domain = TOOL_DOMAINS.get(defn.name, ToolDomain.GENERAL)
    permissions = TOOL_PERMISSIONS.get(defn.name, ())
    return defn.model_copy(
        update={
            "domain": domain,
            "required_permissions": permissions,
        }
    )


READ_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(
    _enrich_definition(defn) for defn in _RAW_READ_TOOL_DEFINITIONS
)

WRITE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(
    _enrich_definition(defn) for defn in _RAW_WRITE_TOOL_DEFINITIONS
)

SENSITIVE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(
    _enrich_definition(defn) for defn in _RAW_SENSITIVE_TOOL_DEFINITIONS
)

ALL_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    READ_TOOL_DEFINITIONS + WRITE_TOOL_DEFINITIONS + SENSITIVE_TOOL_DEFINITIONS
)
