"""Execute allowlisted tool calls with READ/WRITE/SENSITIVE policy."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from app.core.exceptions import AppError
from app.idempotency import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    build_idempotency_key,
)
from app.integrations.retailer_client import RetailerClient
from app.observability import AuditTrail, MetricsRegistry
from app.observability.events import TOOL_EXECUTION, emit_event
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
        idempotency_store: IdempotencyStore | None = None,
        audit_trail: AuditTrail | None = None,
        metrics: MetricsRegistry | None = None,
        insight_cache: Any = None,
    ) -> None:
        self._registry = registry
        self._retailer = retailer
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._audit_trail = audit_trail
        self._metrics = metrics
        self._insight_cache = insight_cache

    async def execute_reads(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        allowed_names: Collection[str],
        session_id: str | None = None,
        user_id: str | None = None,
        question: str = "",
        parallel: bool = False,
        tool_timeout_seconds: float | None = None,
        on_tool_complete: (
            Callable[[ToolCall, ToolResult], Awaitable[None]] | None
        ) = None,
    ) -> list[ToolResult]:
        if parallel and len(tool_calls) > 1:
            return await self._execute_reads_parallel(
                tool_calls,
                access_token=access_token,
                store_id=store_id,
                allowed_names=allowed_names,
                session_id=session_id,
                user_id=user_id,
                question=question,
                parallel=True,
                tool_timeout_seconds=tool_timeout_seconds,
                on_tool_complete=on_tool_complete,
            )
        return await self._execute_reads_parallel(
            tool_calls,
            access_token=access_token,
            store_id=store_id,
            allowed_names=allowed_names,
            session_id=session_id,
            user_id=user_id,
            question=question,
            parallel=False,
            tool_timeout_seconds=tool_timeout_seconds,
            on_tool_complete=on_tool_complete,
        )

    async def _execute_reads_parallel(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        allowed_names: Collection[str],
        session_id: str | None,
        user_id: str | None,
        question: str,
        parallel: bool = True,
        tool_timeout_seconds: float | None = None,
        on_tool_complete: (
            Callable[[ToolCall, ToolResult], Awaitable[None]] | None
        ) = None,
    ) -> list[ToolResult]:
        for call in tool_calls:
            _assert_allowed(call, allowed_names)
            _assert_request_store(call, store_id)
            definition = self._registry.get_definition(call.name)
            if definition.risk != ToolRisk.READ:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=f"Tool '{call.name}' is not auto-executable as read",
                    status_code=500,
                )

        if self._metrics is not None and parallel:
            self._metrics.record_parallel_batch(len(tool_calls))

        context = ToolContext(
            access_token=access_token,
            store_id=store_id,
            retailer=self._retailer,
            question=question,
            insight_cache=self._insight_cache,
        )
        timeout = min(tool_timeout_seconds or 5.0, 5.0)

        async def _one(call: ToolCall) -> ToolResult:
            try:
                res = await asyncio.wait_for(
                    self._run_read(
                        call,
                        context=context,
                        allowed_names=allowed_names,
                        store_id=store_id,
                        session_id=session_id,
                        user_id=user_id,
                        skip_prechecks=True,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                logger.warning("Tool %s timed out after %ss", call.name, timeout)
                res = ToolResult(
                    tool=call.name,
                    success=False,
                    data={
                        "code": "TOOL_TIMEOUT",
                        "message": (f"Tool '{call.name}' timed out after {timeout}s"),
                    },
                )
            except asyncio.CancelledError:
                raise
            except AppError as exc:
                res = ToolResult(
                    tool=call.name,
                    success=False,
                    data={"code": exc.code, "message": exc.message},
                )
            except Exception:
                logger.exception("Parallel read failed", extra={"tool": call.name})
                res = ToolResult(
                    tool=call.name,
                    success=False,
                    data={
                        "code": "RETAILER_UNAVAILABLE",
                        "message": "Tool execution failed",
                    },
                )
            if on_tool_complete is not None:
                try:
                    await on_tool_complete(call, res)
                except Exception:
                    logger.exception(
                        "on_tool_complete callback error for %s", call.name
                    )
            return res

        if parallel and len(tool_calls) > 1:
            gathered = await asyncio.gather(
                *[_one(call) for call in tool_calls],
                return_exceptions=True,
            )
        else:
            gathered = []
            for call in tool_calls:
                try:
                    res = await _one(call)
                    gathered.append(res)
                except BaseException as exc:
                    gathered.append(exc)
        results: list[ToolResult] = []
        for call, item in zip(tool_calls, gathered, strict=True):
            if isinstance(item, asyncio.CancelledError):
                raise item
            if isinstance(item, BaseException):
                results.append(
                    ToolResult(
                        tool=call.name,
                        success=False,
                        data={
                            "code": "RETAILER_UNAVAILABLE",
                            "message": "Tool execution failed",
                        },
                    )
                )
            else:
                results.append(item)
        return results

    async def execute_writes(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        session_id: str,
        user_id: str,
        allowed_names: Collection[str],
        prior_successful_drafts: int = 0,
    ) -> list[ToolResult]:
        """prior_successful_drafts: drafts already created earlier in this
        same user turn (multi-round tool loop) so the one-draft-per-turn
        guard spans rounds."""
        return await self._execute(
            tool_calls,
            access_token=access_token,
            store_id=store_id,
            allowed_risk=ToolRisk.WRITE,
            session_id=session_id,
            user_id=user_id,
            prior_draft_calls=prior_successful_drafts,
            allowed_names=allowed_names,
        )

    async def execute_confirmations(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        session_id: str,
        user_id: str,
        confirmation_id: str,
        business_idempotency_key: str | None = None,
    ) -> list[ToolResult]:
        """Run SENSITIVE tools only after an approved confirmation token."""
        if not tool_calls:
            return []

        context = ToolContext(
            access_token=access_token,
            store_id=store_id,
            retailer=self._retailer,
        )
        results: list[ToolResult] = []
        for call in tool_calls:
            _assert_request_store(call, store_id)
            definition = self._registry.get_definition(call.name)
            if definition.risk != ToolRisk.SENSITIVE:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=(f"Tool '{call.name}' is not confirmation-executable"),
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

            key = business_idempotency_key or build_idempotency_key(
                session_id=session_id,
                tool_name=call.name,
                arguments={
                    **call.arguments,
                    "_confirmationId": confirmation_id,
                },
            )
            cached = await self._idempotency.get(key)
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
                results.append(cached)
                continue

            arguments = dict(call.arguments)
            if call.name in {
                "ledger_credit",
                "ledger_debit",
                "record_customer_payment",
                "add_stock",
                "create_expense",
                "create_purchase_order",
            }:
                arguments["idempotencyKey"] = key
            result = await handler(arguments, context)
            await self._idempotency.put(key, result)
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
            results.append(result)
        return results

    async def _execute(
        self,
        tool_calls: list[ToolCall],
        *,
        access_token: str,
        store_id: str,
        allowed_risk: ToolRisk,
        session_id: str | None,
        user_id: str | None,
        allowed_names: Collection[str],
        prior_draft_calls: int = 0,
        question: str = "",
    ) -> list[ToolResult]:
        if not tool_calls:
            return []

        context = ToolContext(
            access_token=access_token,
            store_id=store_id,
            retailer=self._retailer,
            question=question,
            insight_cache=self._insight_cache,
        )
        results: list[ToolResult] = []
        draft_calls_seen = prior_draft_calls
        for call in tool_calls:
            _assert_allowed(call, allowed_names)
            _assert_request_store(call, store_id)
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
            # Policy: at most one invoice draft per turn — LLMs sometimes emit
            # duplicate draft calls with slightly different args, which the
            # args-hash idempotency cache cannot catch.
            if call.name == "create_invoice_draft":
                draft_calls_seen += 1
                if draft_calls_seen > 1:
                    results.append(
                        ToolResult(
                            tool=call.name,
                            success=False,
                            data={
                                "code": "DUPLICATE_DRAFT_CALL",
                                "message": (
                                    "Only one invoice draft can be created "
                                    "per message; extra draft call skipped"
                                ),
                            },
                        )
                    )
                    continue
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
                result = await self._run_read(
                    call,
                    context=context,
                    allowed_names=allowed_names,
                    store_id=store_id,
                    session_id=session_id,
                    user_id=user_id,
                    handler=handler,
                    skip_prechecks=True,
                )
            results.append(result)
        return results

    async def _run_read(
        self,
        call: ToolCall,
        *,
        context: ToolContext,
        allowed_names: Collection[str],
        store_id: str,
        session_id: str | None,
        user_id: str | None,
        handler=None,
        skip_prechecks: bool = False,
    ) -> ToolResult:
        started = time.perf_counter()
        if not skip_prechecks:
            _assert_allowed(call, allowed_names)
            _assert_request_store(call, store_id)
            definition = self._registry.get_definition(call.name)
            if definition.risk != ToolRisk.READ:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=(f"Tool '{call.name}' is not auto-executable as read"),
                    status_code=500,
                )
        if handler is None:
            try:
                handler = self._registry.get_handler(call.name)
            except KeyError as exc:
                raise AppError(
                    code="TOOL_NOT_EXECUTABLE",
                    message=f"Tool '{call.name}' has no handler",
                    status_code=500,
                ) from exc

        if inspect.iscoroutinefunction(handler):
            result = await handler(call.arguments, context)
        else:
            result = await asyncio.to_thread(handler, call.arguments, context)
        # Read tools: at most one retry on ambiguous Retailer errors.
        if (
            not result.success
            and isinstance(result.data, dict)
            and result.data.get("code") in {"RETAILER_TIMEOUT", "RETAILER_UNAVAILABLE"}
        ):
            if inspect.iscoroutinefunction(handler):
                result = await handler(call.arguments, context)
            else:
                result = await asyncio.to_thread(handler, call.arguments, context)
        latency_ms = (time.perf_counter() - started) * 1000
        self._audit(
            session_id=session_id,
            user_id=user_id,
            store_id=store_id,
            tool=call.name,
            success=result.success,
            error_code=_error_code(result),
            idempotency_key=None,
            cache_hit=None,
            latency_ms=latency_ms,
        )
        return result

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
        cached = await self._idempotency.get(key)
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

        result = await handler(dict(call.arguments), context)
        await self._idempotency.put(key, result)
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

    def _audit(
        self,
        *,
        session_id: str | None,
        user_id: str | None,
        store_id: str,
        tool: str,
        success: bool,
        error_code: str | None,
        idempotency_key: str | None,
        cache_hit: bool | None,
        latency_ms: float | None = None,
    ) -> None:
        # Never log phones, amounts, or free-text notes (rule.md / PII).
        event = {
            "sessionId": session_id,
            "userId": user_id,
            "storeId": store_id,
            "tool": tool,
            "success": success,
            "errorCode": error_code,
            "idempotencyKeyPrefix": (idempotency_key[:40] if idempotency_key else None),
            "cacheHit": cache_hit,
        }
        event_with_name = {"event": TOOL_EXECUTION, **event}
        # Full audit goes to the trail file; logs stay slim (ids already in
        # correlation). Successes are DEBUG — chat.request lists tools_called.
        emit_event(
            TOOL_EXECUTION,
            level=logging.WARNING if not success else logging.DEBUG,
            tool=tool,
            success=success,
            errorCode=error_code,
            cacheHit=cache_hit,
        )
        if self._audit_trail is not None:
            self._audit_trail.append(event_with_name)
        if self._metrics is not None:
            self._metrics.record_tool(tool, success=success, latency_ms=latency_ms)


def _assert_allowed(call: ToolCall, allowed_names: Collection[str]) -> None:
    """Reject a tool the turn's capability set did not include.

    Hiding the schema from the model is not enough. This runs before
    the handler and before any Retailer call.
    """
    if call.name not in allowed_names:
        raise AppError(
            code="TOOL_NOT_ALLOWED",
            message=f"Tool '{call.name}' is not allowlisted",
            status_code=400,
        )


def _assert_request_store(call: ToolCall, store_id: str) -> None:
    """Reject a model-supplied store id that is not the request store.

    Handlers call Retailer with ToolContext.store_id. This check stops a
    mismatched argument from running under the caller's token.
    """
    supplied = call.arguments.get("storeId")
    if not isinstance(supplied, str):
        return
    if supplied != store_id:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool storeId must match the chat request storeId",
            status_code=400,
        )


def _error_code(result: ToolResult) -> str | None:
    if result.success or not isinstance(result.data, dict):
        return None
    code = result.data.get("code")
    return code if isinstance(code, str) else None
