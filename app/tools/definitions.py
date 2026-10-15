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
    "description": "Indian 10-digit mobile number",
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
        description="Live stock totals (SKUs, qty, low/out of stock).",
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
            "List the user's accessible stores (name, id) and mark which "
            "one is active. Use for store name, store count, or which "
            "stores they have."
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
            "customers in last 7/15/30 days (and longer windows)."
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

WRITE_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="create_customer",
        description=(
            "Create customer (name + phone or email from user). "
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
            "Update customer by real ObjectId (name + phone or email)."
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
)
