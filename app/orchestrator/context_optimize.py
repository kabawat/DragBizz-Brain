"""Phase 7: continue-round schema narrowing and model-facing compaction."""

from __future__ import annotations

import json
from typing import Any

from app.rag.chunker import estimate_tokens
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolDefinition, ToolResult, ToolRisk
from app.tools.registry import ToolRegistry

# After Phase 3 projection; client egress still uses full projection.
_MODEL_MAX_LIST = 8
_MODEL_MAX_LEDGER = 15


def tools_for_continue(
    tools: list[ToolDefinition],
    *,
    registry: ToolRegistry,
    results: list[ToolResult],
    staged_sensitive: bool,
) -> list[ToolDefinition]:
    """Narrow Phase 2 allowlist schemas for the next tool-bearing round.

    Drops tools that cannot help anymore (e.g. draft already created).
    Never returns empty while the caller still allows tools — fail-open to
    the original set. Final synthesis must pass tools=None separately.
    """
    if staged_sensitive or not tools:
        return []

    allowed = {tool.name for tool in tools}
    success_by_tool = {
        result.tool: result.success for result in results if result.success
    }

    remaining = set(allowed)
    if success_by_tool.get("create_invoice_draft"):
        remaining.discard("create_invoice_draft")
        remaining.discard("create_customer")
    if success_by_tool.get("update_invoice_draft"):
        remaining.discard("create_invoice_draft")

    has_product = bool(success_by_tool.get("search_product"))
    has_customer = bool(
        success_by_tool.get("search_customer")
        or success_by_tool.get("create_customer")
    )
    write_names = {
        name
        for name in remaining
        if registry.get_definition(name).risk == ToolRisk.WRITE
    }
    if has_product and has_customer and write_names:
        for name in list(remaining):
            if (
                registry.get_definition(name).risk == ToolRisk.READ
                and name not in {"search_product", "search_customer"}
            ):
                remaining.discard(name)
        if (
            "create_invoice_draft" in remaining
            or "update_invoice_draft" in remaining
        ):
            remaining.discard("search_product")
            remaining.discard("search_customer")

    selected = [tool for tool in tools if tool.name in remaining]
    return selected or list(tools)


def compact_result_for_model(result: ToolResult) -> ToolResult:
    """Shrink projected data for LLM tool messages only (not client egress)."""
    data = result.data
    if not isinstance(data, dict) or not result.success:
        return result
    if data.get("status") == "pending_confirmation":
        return result

    out = dict(data)
    if result.tool in {
        "search_product",
        "search_supplier",
        "payment_history",
        "search_customer",
        "stock_items",
        "list_invoices",
        "list_expenses",
        "list_sales_orders",
        "list_purchase_orders",
        "top_customers",
    }:
        _truncate_list_field(out, "items", _MODEL_MAX_LIST)
        _truncate_list_field(out, "suppliers", _MODEL_MAX_LIST)
        _truncate_list_field(out, "invoices", _MODEL_MAX_LIST)
        _truncate_list_field(out, "expenses", _MODEL_MAX_LIST)
        _truncate_list_field(out, "orders", _MODEL_MAX_LIST)
    if result.tool in {"invoice_detailed_analytics", "customer_detailed_analytics"}:
        for list_key in (
            "statusBreakdown",
            "paymentBreakdown",
            "trends",
            "hourly",
            "dailyTrends",
        ):
            val = out.get(list_key)
            if isinstance(val, list):
                _truncate_list_field(out, list_key, _MODEL_MAX_LIST)
    if result.tool == "search_customer":
        ledger = out.get("ledger")
        if isinstance(ledger, dict):
            ledger = dict(ledger)
            if _truncate_list_field(ledger, "entries", _MODEL_MAX_LEDGER):
                out["ledger"] = ledger
        # Downloads are client UI; model only needs availability.
        if isinstance(out.get("downloads"), dict):
            out["downloads"] = {"available": True}
    return ToolResult(tool=result.tool, success=result.success, data=out)


def compact_conversation_for_next_round(
    conversation: list[ChatMessage],
) -> tuple[list[ChatMessage], int]:
    """Strip large Documentation blocks and compact stale tool JSON.

    Returns (messages, estimated_tokens_removed) using the local estimator.
    """
    if not conversation:
        return conversation, 0
    removed = 0
    out: list[ChatMessage] = []
    tool_indexes = [
        index
        for index, message in enumerate(conversation)
        if message.role == "tool"
    ]
    keep_from = tool_indexes[-6] if len(tool_indexes) > 6 else -1

    for index, message in enumerate(conversation):
        if index == 0 and message.role == "system":
            stripped, delta = _strip_documentation(message.content)
            removed += delta
            out.append(
                message.model_copy(update={"content": stripped})
                if delta
                else message
            )
            continue
        if message.role == "tool" and keep_from >= 0 and index < keep_from:
            compacted, delta = _compact_tool_message(message.content)
            removed += delta
            out.append(
                message.model_copy(update={"content": compacted})
                if delta
                else message
            )
            continue
        out.append(message)
    return out, removed


def _truncate_list_field(
    data: dict[str, Any], key: str, limit: int
) -> bool:
    items = data.get(key)
    if not isinstance(items, list) or len(items) <= limit:
        return False
    data[key] = items[:limit]
    data["truncated"] = True
    return True


def _strip_documentation(content: str) -> tuple[str, int]:
    marker = "\nDocumentation:\n"
    if marker not in content:
        return content, 0
    head, _, docs = content.partition(marker)
    # Tiny docs can be smaller than the stub; leave them alone.
    if estimate_tokens(docs) < 40:
        return content, 0
    stub = (
        head
        + "\nDocumentation: (earlier turn; use tool results for live data)\n"
    )
    removed = max(0, estimate_tokens(content) - estimate_tokens(stub))
    return stub, removed


def _compact_tool_message(content: str) -> tuple[str, int]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content, 0
    if not isinstance(payload, dict):
        return content, 0
    data = payload.get("data")
    if not isinstance(data, dict):
        return content, 0
    slim: dict[str, Any] = {
        "tool": payload.get("tool"),
        "success": payload.get("success"),
        "untrusted": True,
        "data": _ids_only(data),
    }
    text = json.dumps(slim, ensure_ascii=False)
    removed = max(0, estimate_tokens(content) - estimate_tokens(text))
    return text, removed


def _ids_only(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "id",
        "customerId",
        "supplierId",
        "invoiceId",
        "status",
        "confirmationId",
        "draftId",
    ):
        if key in data:
            out[key] = data[key]
    items = data.get("items")
    if isinstance(items, list):
        refs: list[dict[str, Any]] = []
        for item in items[:_MODEL_MAX_LIST]:
            if not isinstance(item, dict):
                continue
            ref = {k: item[k] for k in ("id", "name", "sku") if k in item}
            if ref:
                refs.append(ref)
        if refs:
            out["items"] = refs
    suppliers = data.get("suppliers")
    if isinstance(suppliers, list):
        sup_refs: list[dict[str, Any]] = []
        for s in suppliers[:_MODEL_MAX_LIST]:
            if not isinstance(s, dict):
                continue
            sup_ref = {
                k: s[k]
                for k in ("id", "name", "companyName")
                if k in s
            }
            if sup_ref:
                sup_refs.append(sup_ref)
        if sup_refs:
            out["suppliers"] = sup_refs
    return out or {"compacted": True}
