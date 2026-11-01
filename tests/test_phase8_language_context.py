from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.retailer_client import RetailerResponse
from app.orchestrator.tool_selector import resolve_turn_intent
from app.tools.context import ToolContext
from app.tools.handlers.read_tools import product_search_queries, search_product

PRODUCT_ID = "6ad4b6206f4697221df5f87f"
STORE_ID = "6ad49964d5cb7a1b29d4bb7b"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("aata", ["aata", "atta"]),
        ("sarso tel", ["sarso tel", "mustard oil"]),
        ("सरसों तेल", ["सरसों तेल", "mustard oil"]),
        ("doodh", ["doodh", "milk"]),
        ("Amul Cheese", ["Amul Cheese"]),
    ],
)
def test_product_search_query_variants_are_bounded_and_preserve_original(
    query: str, expected: list[str]
) -> None:
    assert product_search_queries(query) == expected


@pytest.mark.asyncio
async def test_product_search_retries_common_hinglish_variant_only_after_miss() -> None:
    retailer = AsyncMock()
    retailer.get_products.side_effect = [
        RetailerResponse(status_code=200, body={"data": []}),
        RetailerResponse(
            status_code=200,
            body={
                "data": [
                    {
                        "id": PRODUCT_ID,
                        "name": "Aashirvaad Atta",
                        "sku": "ATTA-5KG",
                        "sellingPrice": None,
                        "pricing": {"sellingPrice": 265, "uom": "bag"},
                        "taxRate": None,
                        "gstInfo": {"gstRate": 5},
                    }
                ]
            },
        ),
    ]
    context = ToolContext(retailer=retailer, access_token="token", store_id=STORE_ID)

    result = await search_product({"query": "Aashirvaad aata"}, context)

    assert result.success is True
    assert result.data["items"][0]["id"] == PRODUCT_ID
    assert result.data["items"][0]["sellingPrice"] == 265
    assert result.data["items"][0]["taxRate"] == 5
    assert [call.kwargs["query"] for call in retailer.get_products.await_args_list] == [
        "Aashirvaad aata",
        "Aashirvaad atta",
    ]


@pytest.mark.asyncio
async def test_product_rate_lookup_joins_sellable_variant_price_and_sku() -> None:
    retailer = AsyncMock()
    retailer.get_products.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": [
                {
                    "id": PRODUCT_ID,
                    "name": "Aashirvaad Shudh Chakki Whole Wheat Atta",
                    "sku": None,
                    "sellingPrice": None,
                    "pricing": {"sellingPrice": None},
                }
            ]
        },
    )
    retailer.get_variants.return_value = RetailerResponse(
        status_code=200,
        body={
            "data": [
                {
                    "id": "6ad4b6206f4697221df5f880",
                    "displayName": "5 kg",
                    "sku": "AASHIRVAAD-ATTA-5KG",
                    "sellingPrice": 239,
                    "mrp": 250,
                    "status": "ACTIVE",
                    "isDefault": True,
                }
            ]
        },
    )
    context = ToolContext(
        retailer=retailer,
        access_token="token",
        store_id=STORE_ID,
        question="Aashirvaad aata ka rate batao",
    )

    result = await search_product({"query": "Aashirvaad aata"}, context)

    assert result.success is True
    item = result.data["items"][0]
    assert item["sellingPrice"] == 239
    assert item["sku"] == "AASHIRVAAD-ATTA-5KG"
    assert item["variants"][0]["name"] == "5 kg"


@pytest.mark.parametrize(
    "query",
    [
        "maggi ka rate batao",
        "atta ka price check karo",
        "तेल ka stock kitna hai",
        "bill dikhao",
        "aaj ka kharcha batao",
    ],
)
def test_hinglish_and_devanagari_operational_queries_route_to_reads(query: str) -> None:
    available = {
        "search_product",
        "stock_summary",
        "invoice_summary",
        "list_invoices",
        "expense_summary",
    }

    intent = resolve_turn_intent(query, available=available)

    assert intent.routing == "tools"
    assert intent.tool_names
    assert not (intent.tool_names & {"create_expense", "create_invoice_draft"})


def test_context_follow_up_keeps_prior_write_intent_but_does_not_execute_it() -> None:
    intent = resolve_turn_intent(
        "cash me kar do",
        available={"create_expense", "update_expense", "expense_summary"},
        prior_user_texts=["chai ka 20 rupaye ka kharcha draft karo"],
    )

    assert "create_expense" in intent.tool_names
    assert intent.routing in {"tools", "unknown"}
