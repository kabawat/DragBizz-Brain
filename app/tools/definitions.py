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
        description=(
            "Search live products in the active store by name or SKU "
            "(current price, stock, status)"
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
                    "description": "Product search text",
                },
            },
            "required": ["storeId", "query"],
        },
    ),
    ToolDefinition(
        name="today_sale",
        description=(
            "Get today's live sales numbers (revenue, profit, bill count) "
            "for the active store"
        ),
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
        description=(
            "Get current stock totals (SKUs, quantities, low/out of stock) "
            "for the active store"
        ),
        risk=ToolRisk.READ,
        parameters={
            "type": "object",
            "additionalProperties": False,
            "properties": {"storeId": _STORE_ID_PROP},
            "required": ["storeId"],
        },
    ),
    ToolDefinition(
        name="payment_history",
        description=(
            "Get recent live customer payment records for the active store"
        ),
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
            "Create a customer in the active store. Requires name and at least "
            "one of phone or email supplied by the user — never invent or "
            "suggest name/phone/email. Never invent customer IDs."
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
            "Update an existing customer by ObjectId. Requires name and at "
            "least one of phone or email. Use a real customer id — never invent."
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
            "Create a DRAFT invoice only (does not release or deduct stock). "
            "Each item needs a real product ObjectId from search_product and "
            "quantity >= 1. Optional customer ObjectId; walk-in if omitted."
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
        name="ledger_credit",
        description=(
            "Record a customer PAYMENT (credit on khata: customer paid us). "
            "Requires real customer ObjectId and amount > 0."
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
            "Record a customer DEBIT (increases amount due on khata). "
            "Requires real customer ObjectId and amount > 0. "
            "Not an invoice release."
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
