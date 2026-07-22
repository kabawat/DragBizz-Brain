from __future__ import annotations

from app.core.exceptions import AppError
from app.integrations.retailer_client import RetailerClient
from app.schemas.tool import ToolCall, ToolResult, ToolRisk
from app.tools.context import ToolContext
from app.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(
        self, *, registry: ToolRegistry, retailer: RetailerClient
    ) -> None:
        self._registry = registry
        self._retailer = retailer

    async def execute_reads(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
    ) -> list[ToolResult]:
        if not tool_calls:
            return []

        context = ToolContext(
            access_token=access_token,
            store_id=store_id,
            retailer=self._retailer,
        )
        results: list[ToolResult] = []
        for call in tool_calls:
            definition = self._registry.get_definition(call.name)
            if definition.risk != ToolRisk.READ:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=f"Tool '{call.name}' is not auto-executable",
                    status_code=500,
                )
            try:
                handler = self._registry.get_handler(call.name)
            except KeyError as exc:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=f"Tool '{call.name}' has no handler",
                    status_code=500,
                ) from exc
            results.append(await handler(call.arguments, context))
        return results
