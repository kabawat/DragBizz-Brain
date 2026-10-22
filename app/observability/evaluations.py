"""Deterministic evaluations for DragBizz Brain business operations.

Validates tool-result schema integrity, mathematical consistency, and
business logic accuracy without running extra LLM calls.
"""

from __future__ import annotations

import logging

from app.observability.middleware_telemetry import submit_agent_evaluation
from app.schemas.tool import ToolCall, ToolResult

logger = logging.getLogger(__name__)


def evaluate_turn_correctness(
    *,
    tool_calls: list[ToolCall],
    tool_results: list[ToolResult],
    message: str,
) -> dict[str, float]:
    """Run deterministic evaluations on tool executions and final response.

    Returns a mapping of metric names to scores (0.0 to 1.0).
    """
    scores: dict[str, float] = {}

    # 1. Tool execution integrity
    if tool_calls:
        success_count = sum(1 for r in tool_results if r.success)
        tool_integrity = success_count / len(tool_calls)
        scores["tool_execution_integrity"] = round(tool_integrity, 2)
        submit_agent_evaluation(
            name="tool_execution_integrity",
            value=tool_integrity,
            comment=f"Executed {success_count}/{len(tool_calls)} tools successfully",
        )

    # 2. Financial & Ledger consistency
    for res in tool_results:
        if not res.success or not isinstance(res.data, dict):
            continue

        # Check customer dues / accounts
        if res.tool in {"list_customer_accounts", "get_customer_ledger"}:
            accounts = res.data.get("accounts") or res.data.get("items") or []
            valid = True
            if isinstance(accounts, list):
                for acc in accounts:
                    if isinstance(acc, dict) and "totalDue" in acc:
                        try:
                            due = float(acc["totalDue"])
                            if due < 0:
                                valid = False
                        except (ValueError, TypeError):
                            valid = False
            score = 1.0 if valid else 0.0
            scores["ledger_accuracy"] = score
            submit_agent_evaluation(
                name="ledger_accuracy",
                value=score,
                comment="Customer dues non-negative and correctly formatted",
            )

        # Check today's sales / revenue figures
        if res.tool in {"today_sale", "invoice_summary"}:
            rev = (
                res.data.get("totalRevenue")
                or res.data.get("revenue")
                or res.data.get("netAmount")
            )
            valid = True
            if rev is not None:
                try:
                    rev_val = float(rev)
                    if rev_val < 0:
                        valid = False
                except (ValueError, TypeError):
                    valid = False
            score = 1.0 if valid else 0.0
            scores["revenue_accuracy"] = score
            submit_agent_evaluation(
                name="revenue_accuracy",
                value=score,
                comment="Revenue total numeric and non-negative",
            )

    # 3. Overall response validity
    if message and not message.startswith("AppError"):
        scores["response_validity"] = 1.0
    else:
        scores["response_validity"] = 0.0

    return scores
