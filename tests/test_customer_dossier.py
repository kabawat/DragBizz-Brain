"""Who-is dossier: intent, handler, projection, fast reply, prompt."""

from __future__ import annotations

import asyncio

from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerHttpError, RetailerResponse
from app.orchestrator.dossier_auto import (
    name_list_count,
    try_fast_dossier_turn,
    try_fast_due_list,
    try_fast_name_list,
    try_fast_purchase_rank,
)
from app.orchestrator.tool_selector import extract_who_is_query, resolve_turn_intent
from app.prompts.system.chat import build_chat_system_prompt
from app.schemas.tool import ToolResult
from app.tools.context import ToolContext
from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS, customer_dossier
from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS
from app.tools.projection import project_tool_result
from app.tools.registry import ToolRegistry

STORE = "a" * 24
CUSTOMER = "b" * 24


def _available() -> set[str]:
    names = {item.name for item in READ_TOOL_DEFINITIONS}
    names.update(item.name for item in WRITE_TOOL_DEFINITIONS)
    names.update(item.name for item in SENSITIVE_TOOL_DEFINITIONS)
    return names


def test_who_is_exposes_dossier_not_full_reads() -> None:
    intent = resolve_turn_intent(
        "Kishanlal Bansal kon he?", available=_available()
    )
    assert intent.routing == "tools"
    assert intent.tool_names == frozenset(
        {"customer_dossier", "search_product"}
    )


def test_existing_intents_unchanged() -> None:
    sale = resolve_turn_intent("aaj ki sale", available=_available())
    assert "today_sale" in sale.tool_names
    assert "customer_dossier" not in sale.tool_names

    sale_all = resolve_turn_intent("aaj ki sale sab kuch", available=_available())
    assert "today_sale" in sale_all.tool_names
    assert "customer_dossier" not in sale_all.tool_names

    created = resolve_turn_intent("customer banao", available=_available())
    assert "create_customer" in created.tool_names
    assert "customer_dossier" not in created.tool_names

    udhaar = resolve_turn_intent(
        "vikram ke khate me 100 add kar do", available=_available()
    )
    assert "ledger_debit" in udhaar.tool_names
    assert "search_customer" in udhaar.tool_names


class _Retailer:
    def __init__(
        self,
        customers: list[dict],
        *,
        invoices: list[dict] | None = None,
        invoice_error: bool = False,
    ) -> None:
        self.customers = customers
        self.invoices = invoices or []
        self.invoice_error = invoice_error
        self.invoice_calls = 0

    async def get_customers(self, **_kwargs):
        return RetailerResponse(status_code=200, body={"data": self.customers})

    async def get_invoices(self, **_kwargs):
        self.invoice_calls += 1
        if self.invoice_error:
            raise RetailerHttpError(502, "RETAILER_UNAVAILABLE", "down")
        return RetailerResponse(status_code=200, body={"data": self.invoices})


def _context(retailer: _Retailer) -> ToolContext:
    return ToolContext(
        access_token="token",
        store_id=STORE,
        retailer=retailer,  # type: ignore[arg-type]
        question="Kishanlal kon he?",
    )


def test_dossier_one_match_loads_bills_once() -> None:
    retailer = _Retailer(
        [
            {
                "id": CUSTOMER,
                "name": "Kishanlal Bansal",
                "phone": "9812345678",
                "note": "evening regular",
                "account": {"totalDue": 0, "totalPaid": 10},
            }
        ],
        invoices=[
            {
                "id": "c" * 24,
                "invoiceNumber": "INV-1",
                "totalAmount": 80,
                "createdAt": "2026-10-01T00:00:00Z",
                "gst": {"amount": 12},
                "items": [{"productName": "Paneer", "quantity": 1}],
            }
        ],
    )
    result = asyncio.run(
        customer_dossier({"query": "Kishanlal"}, _context(retailer))
    )
    assert result.success
    assert retailer.invoice_calls == 1
    assert result.data["billsStatus"] == "ok"
    assert result.data["billsScanned"] == 1
    assert result.data["matchCount"] == 1


def test_dossier_two_matches_skip_invoices() -> None:
    retailer = _Retailer(
        [
            {
                "id": CUSTOMER,
                "name": "A",
                "phone": "9812345678",
                "note": "prefers butter",
            },
            {"id": "d" * 24, "name": "A", "phone": "9812345679"},
        ]
    )
    result = asyncio.run(
        customer_dossier({"query": "A"}, _context(retailer))
    )
    assert retailer.invoice_calls == 0
    assert result.data["billsStatus"] == "ambiguous"
    assert result.data["matchCount"] == 2
    assert "note" not in result.data["items"][0]
    assert "memo" not in result.data["items"][0]


def test_dossier_lists_every_name_match() -> None:
    retailer = _Retailer(
        [
            {"id": "d" * 24, "name": "Vikram Sharma", "phone": "9812345678"},
            {
                "id": CUSTOMER,
                "name": "vikram",
                "phone": "7877952898",
                "note": "udhari vala",
            },
        ],
        invoices=[
            {
                "id": "c" * 24,
                "invoiceNumber": "INV-2",
                "totalAmount": 100,
                "createdAt": "2026-10-18T00:00:00Z",
            }
        ],
    )
    result = asyncio.run(
        customer_dossier({"query": "Vikram"}, _context(retailer))
    )
    assert result.data["matchBy"] == "name"
    assert result.data["billsStatus"] == "ambiguous"
    assert result.data["matchCount"] == 2
    assert retailer.invoice_calls == 0
    names = {item["name"] for item in result.data["items"]}
    assert names == {"vikram", "Vikram Sharma"}


def test_name_list_returns_names_without_amounts() -> None:
    assert name_list_count("koi 4 customer ke name bta") == 4
    assert name_list_count("vikram kon he?") is None
    purchase = (
        "koi 4 customer ke name bta jinhone mere se jyada samana liya ho "
        "and kisne kitna purchase kiya vo bhi"
    )
    assert name_list_count(purchase) is None

    class Names(_FastRetailer):
        async def get_customers(self, **_kwargs):
            return RetailerResponse(
                status_code=200,
                body={
                    "data": [
                        {"id": CUSTOMER, "name": "Aditi Kumar", "phone": "9811111111"},
                        {"id": "d" * 24, "name": "Aarav Mishra"},
                        {"id": "c" * 24, "name": "Naresh", "phone": "9602013850"},
                        {"id": "e" * 24, "name": "Jayesh Patel"},
                        {"id": "f" * 24, "name": "Extra"},
                    ]
                },
            )

    outcome = asyncio.run(
        try_fast_name_list(
            question="koi 4 customer ke name bta",
            language="en",
            store_id=STORE,
            access_token="token",
            session_id="sess",
            user_id="user-1",
            allowed_names=frozenset({"search_customer"}),
            executor=ToolExecutor(registry=_registry(), retailer=Names()),
        )
    )
    assert outcome is not None
    assert "Aditi Kumar" in outcome.message
    assert "Jayesh Patel" in outcome.message
    assert "Extra" not in outcome.message
    assert "₹" not in outcome.message


def test_top_customers_ranks_released_bills() -> None:
    question = (
        "koi 4 customer ke name bta jinhone mere se jyada samana liya ho "
        "and kisne kitna purchase kiya vo bhi"
    )
    intent = resolve_turn_intent(question, available=_available())
    assert "top_customers" in intent.tool_names

    class Bills(_FastRetailer):
        async def list_invoices(self, **_kwargs):
            return RetailerResponse(
                status_code=200,
                body={
                    "data": [
                        {
                            "invoiceStatus": "RELEASED",
                            "totalAmount": 100,
                            "customer": {
                                "id": CUSTOMER,
                                "name": "Rajesh Jha",
                                "phone": "9876465111",
                            },
                        },
                        {
                            "invoiceStatus": "RELEASED",
                            "totalAmount": 50,
                            "customer": {
                                "id": CUSTOMER,
                                "name": "Rajesh Jha",
                                "phone": "9876465111",
                            },
                        },
                        {
                            "invoiceStatus": "DRAFT",
                            "totalAmount": 9999,
                            "customer": {
                                "id": "d" * 24,
                                "name": "Draft Only",
                            },
                        },
                        {
                            "invoiceStatus": "RELEASED",
                            "totalAmount": 80,
                            "customer": {
                                "id": "e" * 24,
                                "name": "vikram",
                                "phone": "7877952898",
                            },
                        },
                    ]
                },
            )

    outcome = asyncio.run(
        try_fast_purchase_rank(
            question=question,
            language="en",
            store_id=STORE,
            access_token="token",
            session_id="sess",
            user_id="user-1",
            allowed_names=intent.tool_names,
            executor=ToolExecutor(registry=_registry(), retailer=Bills()),
        )
    )
    assert outcome is not None
    assert "not in this list" not in outcome.message
    assert outcome.message.index("Rajesh Jha") < outcome.message.index("vikram")
    assert "₹150" in outcome.message
    assert "₹80" in outcome.message
    assert "Draft Only" not in outcome.message
    assert "9876465111" in outcome.message


def test_due_list_uses_accounts_not_recent_names() -> None:
    question = "konsa customer ki kitni udhari he list dena to number ya email ke sath"
    intent = resolve_turn_intent(question, available=_available())
    assert "list_customer_accounts" in intent.tool_names

    class Accounts(_FastRetailer):
        async def list_customer_accounts(self, **_kwargs):
            return RetailerResponse(
                status_code=200,
                body={
                    "data": [
                        {
                            "id": "e" * 24,
                            "totalDue": 100,
                            "customer": {
                                "id": CUSTOMER,
                                "name": "vikram",
                                "phone": "7877952898",
                            },
                        },
                        {
                            "id": "f" * 24,
                            "totalDue": 0,
                            "customer": {
                                "id": "d" * 24,
                                "name": "Rohit Sharma",
                                "email": "rohit.sharma@example.com",
                            },
                        },
                        {
                            "id": "c" * 24,
                            "totalDue": 1000,
                            "customer": {
                                "id": "a" * 24,
                                "name": "Rajesh Jha",
                                "phone": "9876465111",
                            },
                        },
                    ]
                },
            )

    outcome = asyncio.run(
        try_fast_due_list(
            question=question,
            language="en",
            store_id=STORE,
            access_token="token",
            session_id="sess",
            user_id="user-1",
            allowed_names=intent.tool_names,
            executor=ToolExecutor(registry=_registry(), retailer=Accounts()),
        )
    )
    assert outcome is not None
    assert outcome.message.index("Rajesh Jha") < outcome.message.index("vikram")
    assert "₹1000" in outcome.message
    assert "₹100" in outcome.message
    assert "Rohit Sharma" not in outcome.message
    assert "7877952898" in outcome.message


def test_who_is_query_drops_quotes() -> None:
    assert extract_who_is_query("vikram' kon he?") == "vikram"


def test_dossier_pages_past_email_matches() -> None:
    class Paged(_Retailer):
        def __init__(self) -> None:
            super().__init__([])
            self.cursors: list[str | None] = []

        async def get_customers(self, **kwargs):
            cursor = kwargs.get("next_cursor")
            self.cursors.append(cursor)
            if not cursor:
                return RetailerResponse(
                    status_code=200,
                    body={
                        "data": [
                            {
                                "id": "d" * 24,
                                "name": "Pratik Dave",
                                "email": "vikrammalani07@example.com",
                            }
                        ],
                        "meta": {
                            "pagination": {
                                "hasNextPage": True,
                                "nextCursor": "cursor-2",
                            }
                        },
                    },
                )
            return RetailerResponse(
                status_code=200,
                body={
                    "data": [
                        {
                            "id": CUSTOMER,
                            "name": "vikram",
                            "phone": "7877952898",
                        }
                    ],
                    "meta": {"pagination": {"hasNextPage": False}},
                },
            )

    retailer = Paged()
    result = asyncio.run(
        customer_dossier({"query": "vikram"}, _context(retailer))
    )
    assert retailer.cursors == [None, "cursor-2"]
    assert result.data["matchCount"] == 1
    assert result.data["items"][0]["name"] == "vikram"
    assert result.data["billsStatus"] == "empty"


def test_dossier_name_beats_email_matches() -> None:
    retailer = _Retailer(
        [
            {
                "id": "d" * 24,
                "name": "Pratik Dave",
                "phone": "9812345678",
                "email": "vikram.dave@example.com",
            },
            {
                "id": CUSTOMER,
                "name": "vikram",
                "phone": "7877952898",
                "email": "other@example.com",
            },
        ],
        invoices=[
            {
                "id": "c" * 24,
                "invoiceNumber": "INV-2",
                "totalAmount": 100,
                "createdAt": "2026-10-18T00:00:00Z",
            }
        ],
    )
    result = asyncio.run(
        customer_dossier({"query": "vikram"}, _context(retailer))
    )
    assert result.data["matchBy"] == "name"
    assert result.data["matchCount"] == 1
    assert result.data["items"][0]["name"] == "vikram"
    assert retailer.invoice_calls == 1


def test_dossier_email_matches_stay_a_list() -> None:
    retailer = _Retailer(
        [
            {
                "id": CUSTOMER,
                "name": "Pratik Dave",
                "email": "vikram@example.com",
            }
        ]
    )
    result = asyncio.run(
        customer_dossier({"query": "vikram"}, _context(retailer))
    )
    assert retailer.invoice_calls == 0
    assert result.data["matchBy"] == "email"
    assert result.data["billsStatus"] == "ambiguous"
    assert result.data["items"][0]["email"] == "vikram@example.com"


def test_dossier_drops_unrelated_names() -> None:
    retailer = _Retailer(
        [
            {"id": CUSTOMER, "name": "Pratik Dave", "phone": "9812345678"},
            {"id": "d" * 24, "name": "Parth Rathore", "phone": "9812345679"},
        ]
    )
    result = asyncio.run(
        customer_dossier({"query": "Vikram"}, _context(retailer))
    )
    assert retailer.invoice_calls == 0
    assert result.data["billsStatus"] == "no_match"
    assert result.data["matchCount"] == 0


def test_dossier_invoice_error_keeps_profile() -> None:
    retailer = _Retailer(
        [{"id": CUSTOMER, "name": "Kishanlal", "phone": "9812345678"}],
        invoice_error=True,
    )
    result = asyncio.run(
        customer_dossier({"query": "Kishanlal"}, _context(retailer))
    )
    assert result.success
    assert result.data["items"][0]["name"] == "Kishanlal"
    assert result.data["billsStatus"] == "unavailable"
    assert result.data["billsError"] == "RETAILER_UNAVAILABLE"


def test_projection_drops_gst_and_caps_lines() -> None:
    items = [{"productName": f"P{i}", "quantity": i + 1} for i in range(6)]
    projected = project_tool_result(
        ToolResult(
            tool="customer_dossier",
            success=True,
            data={
                "matchCount": 1,
                "billsStatus": "ok",
                "billsScanned": 1,
                "items": [
                    {
                        "id": CUSTOMER,
                        "name": "Kishanlal",
                        "note": "evening regular",
                    }
                ],
                "bills": [
                    {
                        "id": "c" * 24,
                        "invoiceNumber": "INV-1",
                        "totalAmount": 80,
                        "date": "2026-10-01",
                        "gst": {"amount": 12},
                        "publicId": "secret-public",
                        "totalProfit": 20,
                        "items": [
                            {
                                "name": line["productName"],
                                "qty": line["quantity"],
                            }
                            for line in items
                        ],
                    }
                ],
            },
        )
    )
    blob = str(projected.data)
    assert "secret-public" not in blob
    assert "totalProfit" not in blob
    assert "gst" not in blob
    assert projected.data["items"][0]["memo"] == "evening regular"
    assert "note" not in projected.data["items"][0]
    assert len(projected.data["bills"][0]["items"]) == 5


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definitions, handlers in (
        (READ_TOOL_DEFINITIONS, READ_TOOL_HANDLERS),
        (WRITE_TOOL_DEFINITIONS, WRITE_TOOL_HANDLERS),
        (SENSITIVE_TOOL_DEFINITIONS, SENSITIVE_TOOL_HANDLERS),
    ):
        for definition in definitions:
            registry.register(definition, handlers[definition.name])
    return registry


class _FastRetailer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_customers(self, **_kwargs):
        self.calls.append("customers")
        return RetailerResponse(
            status_code=200,
            body={
                "data": [
                    {
                        "id": CUSTOMER,
                        "name": "Kishanlal Bansal",
                        "phone": "9812345678",
                        "note": "evening regular",
                        "account": {"totalDue": 0, "totalPaid": 40},
                    }
                ]
            },
        )

    async def get_invoices(self, **_kwargs):
        self.calls.append("invoices")
        return RetailerResponse(
            status_code=200,
            body={
                "data": [
                    {
                        "id": "c" * 24,
                        "invoiceNumber": "INV-9",
                        "totalAmount": 120,
                        "createdAt": "2026-10-02T10:00:00Z",
                        "items": [{"productName": "Paneer", "quantity": 2}],
                    }
                ]
            },
        )


def test_fast_dossier_quotes_bills_not_personality() -> None:
    retailer = _FastRetailer()
    executor = ToolExecutor(registry=_registry(), retailer=retailer)

    async def _once():
        return await try_fast_dossier_turn(
            question="Kishanlal Bansal kon he?",
            language="hi-IN",
            store_id=STORE,
            access_token="token",
            session_id="sess",
            user_id="user-1",
            allowed_names=frozenset({"customer_dossier", "search_product"}),
            executor=executor,
        )

    first = asyncio.run(_once())
    second = asyncio.run(_once())
    assert first is not None and second is not None
    assert first.message == second.message
    assert first.message.startswith("**Kishanlal Bansal**")
    assert "\n## Recent bills\n" in first.message
    assert "### **₹120** · 2026-10-02" in first.message
    assert "- Paneer x2" in first.message
    assert "evening regular" in first.message
    lowered = first.message.lower()
    assert "loves" not in lowered
    assert "enjoys" not in lowered
    assert "prefers" not in lowered
    assert retailer.calls == ["customers", "invoices", "customers", "invoices"]


def test_fast_dossier_lists_ambiguous_without_biography() -> None:
    class Many(_FastRetailer):
        async def get_customers(self, **_kwargs):
            self.calls.append("customers")
            return RetailerResponse(
                status_code=200,
                body={
                    "data": [
                        {
                            "id": CUSTOMER,
                            "name": "Kishanlal",
                            "phone": "9812345678",
                            "note": "Prefers paneer",
                        },
                        {
                            "id": "d" * 24,
                            "name": "Kishanlal",
                            "phone": "9812345679",
                            "note": "Monthly khata customer",
                        },
                    ]
                },
            )

        async def get_invoices(self, **_kwargs):
            raise AssertionError("invoices should not be called")

    outcome = asyncio.run(
        try_fast_dossier_turn(
            question="Kishanlal kon he?",
            language="en",
            store_id=STORE,
            access_token="token",
            session_id="sess",
            user_id="user-1",
            allowed_names=frozenset({"customer_dossier", "search_product"}),
            executor=ToolExecutor(registry=_registry(), retailer=Many()),
        )
    )
    assert outcome is not None
    assert "9812345678" in outcome.message
    assert "9812345679" in outcome.message
    assert "prefers" not in outcome.message.lower()
    assert "khata" not in outcome.message.lower()


def test_dossier_prompt_only_when_tool_offered() -> None:
    search_only = [
        tool for tool in READ_TOOL_DEFINITIONS if tool.name == "search_customer"
    ]
    dossier_only = [
        tool
        for tool in READ_TOOL_DEFINITIONS
        if tool.name == "customer_dossier"
    ]
    search_prompt = build_chat_system_prompt(
        language="hi-IN", store_id=STORE, tools=search_only, routing="tools"
    )
    dossier_prompt = build_chat_system_prompt(
        language="hi-IN", store_id=STORE, tools=dossier_only, routing="tools"
    )
    assert "call customer_dossier" in dossier_prompt
    assert "call customer_dossier" not in search_prompt
    assert "regular timings" not in search_prompt
