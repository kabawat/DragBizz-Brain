from app.schemas.tool import ToolDefinition, ToolRisk

_STORE_ID_PROP = {
    "type": "string",
    "pattern": "^[a-fA-F0-9]{24}$",
    "description": "Active store ObjectId; must match the chat request storeId",
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
