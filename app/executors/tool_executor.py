from __future__ import annotations

import logging

from app.core.exceptions import AppError
from app.idempotency import InMemoryIdempotencyStore, build_idempotency_key
from app.integrations.retailer_client import RetailerClient
from app.schemas.tool import ToolCall, ToolResult, ToolRisk
from app.tools.context import ToolContext
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        retailer: RetailerClient,
        idempotency_store: InMemoryIdempotencyStore | None = None,
    ) -> None:
        self._registry = registry
        self._retailer = retailer
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()

    async def execute_reads(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
    ) -> list[ToolResult]:
        return await self._execute(
            tool_calls,
            access_token=access_token,
            store_id=store_id,
            allowed_risk=ToolRisk.READ,
            session_id=None,
            user_id=None,
        )

    async def execute_writes(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        session_id: str,
        user_id: str,
    ) -> list[ToolResult]:
        return await self._execute(
            tool_calls,
            access_token=access_token,
            store_id=store_id,
            allowed_risk=ToolRisk.WRITE,
            session_id=session_id,
            user_id=user_id,
        )

    async def _execute(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        allowed_risk: ToolRisk,
        session_id: str | None,
        user_id: str | None,
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
            if definition.risk != allowed_risk:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=(
                        f"Tool '{call.name}' is not auto-executable "
                        f"as {allowed_risk.value}"
                    ),
                    status_code=500,
                )
            if definition.risk == ToolRisk.SENSITIVE:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=f"Tool '{call.name}' requires confirmation",
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

            if allowed_risk == ToolRisk.WRITE:
                assert session_id is not None and user_id is not None
                result = await self._run_write(
                    call,
                    handler=handler,
                    context=context,
                    session_id=session_id,
                    user_id=user_id,
                    store_id=store_id,
                )
            else:
                result = await handler(call.arguments, context)
            results.append(result)
        return results

    async def _run_write(
        self,
        call: ToolCall,
        *,
        handler,
        context: ToolContext,
        session_id: str,
        user_id: str,
        store_id: str,
    ) -> ToolResult:
        key = build_idempotency_key(
            session_id=session_id,
            tool_name=call.name,
            arguments=call.arguments,
        )
        cached = self._idempotency.get(key)
        if cached is not None:
            self._audit(
                session_id=session_id,
                user_id=user_id,
                store_id=store_id,
                tool=call.name,
                success=cached.success,
                error_code=_error_code(cached),
                idempotency_key=key,
                cache_hit=True,
            )
            return cached

        arguments = dict(call.arguments)
        if call.name in {"ledger_credit", "ledger_debit"}:
            arguments["idempotencyKey"] = key

        result = await handler(arguments, context)
        self._idempotency.put(key, result)
        self._audit(
            session_id=session_id,
            user_id=user_id,
            store_id=store_id,
            tool=call.name,
            success=result.success,
            error_code=_error_code(result),
            idempotency_key=key,
            cache_hit=False,
        )
        return result

    @staticmethod
    def _audit(
        *,
        session_id: str,
        user_id: str,
        store_id: str,
        tool: str,
        success: bool,
        error_code: str | None,
        idempotency_key: str,
        cache_hit: bool,
    ) -> None:
        # Never log phones, amounts, or free-text notes (rule.md / PII).
        key_prefix = idempotency_key[:40]
        logger.info(
            "Write tool audit",
            extra={
                "audit": {
                    "sessionId": session_id,
                    "userId": user_id,
                    "storeId": store_id,
                    "tool": tool,
                    "success": success,
                    "errorCode": error_code,
                    "idempotencyKeyPrefix": key_prefix,
                    "cacheHit": cache_hit,
                }
            },
        )


def _error_code(result: ToolResult) -> str | None:
    if result.success or not isinstance(result.data, dict):
        return None
    code = result.data.get("code")
    return code if isinstance(code, str) else None
