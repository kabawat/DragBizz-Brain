from app.schemas.tool import ToolDefinition, ToolRisk

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

READ_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
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
        name="payment_history",
        description=(
            "Recent customer payments for this store. Not one customer's "
            "ledger lines."
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
            "List payment reminders sent for this store (optional "
            "customerId filter)."
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

WRITE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
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

SENSITIVE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
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
)
