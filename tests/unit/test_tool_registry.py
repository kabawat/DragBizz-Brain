import pytest

from app.schemas.tool import ToolDefinition, ToolResult, ToolRisk
from app.tools.context import ToolContext
from app.tools.registry import ToolRegistry


async def search_product_handler(arguments: dict, context: ToolContext) -> ToolResult:
    del context
    return ToolResult(
        tool="search_product",
        success=True,
        data={"query": arguments["query"]},
    )


def test_registry_returns_allowlisted_tool_contract() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(
        name="search_product",
        description="Search products in the active store",
        risk=ToolRisk.READ,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "storeId": {"type": "string"},
            },
            "required": ["query", "storeId"],
        },
    )

    registry.register(definition, search_product_handler)

    assert registry.get_definition("search_product") == definition
    assert registry.get_handler("search_product") is search_product_handler
    assert registry.definitions() == (definition,)


def test_registry_rejects_unknown_tool() -> None:
    registry = ToolRegistry()

    with pytest.raises(KeyError, match="not registered"):
        registry.get_handler("delete_everything")


def test_definitions_for_returns_sorted_subset() -> None:
    registry = ToolRegistry()
    sale = ToolDefinition(
        name="today_sale",
        description="Today sales",
        risk=ToolRisk.READ,
        parameters={"type": "object", "properties": {}},
    )
    stock = ToolDefinition(
        name="stock_summary",
        description="Stock summary",
        risk=ToolRisk.READ,
        parameters={"type": "object", "properties": {}},
    )
    registry.register_definition(sale)
    registry.register_definition(stock)

    assert registry.definitions_for({"stock_summary", "missing"}) == (stock,)
    assert registry.definitions_for([]) == ()
