from app.schemas.tool import ToolDefinition, ToolRisk

_STORE_ID_PROP = {
    "type": "string",
    "pattern": "^[a-fA-F0-9]{24}$",
    "description": "Active store ObjectId; must match the chat request storeId",
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
            "Search customers by name/phone/email; returns real ObjectIds. "
            "Use before create, bill, or khata."
        ),
        risk=ToolRisk.READ,
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
        description="Recent live customer payment records.",
        risk=ToolRisk.READ,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
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
    ToolDefinition(
        name="ledger_credit",
        description="Record customer PAYMENT (khata credit). Real customerId + amount>0.",
        risk=ToolRisk.WRITE,
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
                    "description": "Payment amount in INR",
                },
                "notes": {
                    "type": "string",
                    "maxLength": 500,
                },
            },
            "required": ["storeId", "customerId", "amount"],
        },
    ),
    ToolDefinition(
        name="ledger_debit",
        description=(
            "Record customer DEBIT on khata (increases due). "
            "Real customerId + amount>0. Not invoice release."
        ),
        risk=ToolRisk.WRITE,
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
                    "description": "Debit amount in INR",
                },
                "notes": {
                    "type": "string",
                    "maxLength": 500,
                },
            },
            "required": ["storeId", "customerId", "amount"],
        },
    ),
)

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
)
