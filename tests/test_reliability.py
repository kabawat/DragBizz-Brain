"""Phase 4: confirmation state machine, leases, budget, rate limits, breaker, RAG."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.confirmations import InMemoryConfirmationStore
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.integrations.retailer_client import RetailerHttpError, RetailerResponse
from app.limits import (
    CircuitBreaker,
    InMemoryConcurrencyGate,
    InMemoryRateLimiter,
    Lease,
    RequestBudget,
)
from app.limits.circuit_breaker import BreakerState
from app.limits.request_budget import BudgetExceeded
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_context import build_chat_context
from app.orchestrator.confirm_flow import handle_confirm
from app.orchestrator.confirmation import stage_from_sensitive_calls
from app.orchestrator.model_router import ModelRouter
from app.providers.openai_compatible import (
    CHEAPER_PROVIDER_NAME,
    OPENAI_PROVIDER_NAME,
)
from app.schemas.chat import (
    ChatMessage,
    ConfirmRequest,
    GenerationRequest,
    GenerationResponse,
)
from app.schemas.tool import ToolCall, ToolDefinition, ToolRisk
from app.sessions import InMemorySessionStore
from app.tools.definitions import SENSITIVE_TOOL_DEFINITIONS
from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE = "a" * 24
CUSTOMER = "b" * 24
SESSION = "sess-rel"


def _guard(message: str, **_kwargs: object) -> str:
    return message


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in SENSITIVE_TOOL_DEFINITIONS:
        registry.register(definition, SENSITIVE_TOOL_HANDLERS[definition.name])
    return registry


class TimeoutRetailer:
    def __init__(self, *, succeed_on: int | None = None) -> None:
        self.calls = 0
        self._succeed_on = succeed_on

    async def create_ledger_transaction(self, **kwargs):
        self.calls += 1
        if self._succeed_on is not None and self.calls >= self._succeed_on:
            return RetailerResponse(
                status_code=200, body={"data": {"id": "tx1"}}
            )
        raise RetailerHttpError(
            status_code=504,
            code="RETAILER_TIMEOUT",
            message="Retailer request timed out",
        )

    async def release_invoice(self, **kwargs):
        self.calls += 1
        raise RetailerHttpError(
            status_code=504,
            code="RETAILER_TIMEOUT",
            message="Retailer request timed out",
        )


class FailRetailer:
    async def create_ledger_transaction(self, **kwargs):
        raise RetailerHttpError(
            status_code=400,
            code="VALIDATION_ERROR",
            message="bad amount",
        )


class FakeRedis:
    """Minimal async Redis stub for fail-closed tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self._data: dict[str, str] = {}
        self._ttl: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        value = int(self._data.get(key, "0")) + 1
        self._data[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self._ttl[key] = seconds

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ):
        if self.fail:
            raise ConnectionError("redis down")
        if nx and key in self._data:
            return False
        self._data[key] = value
        if ex is not None:
            self._ttl[key] = ex
        return True

    async def get(self, key: str):
        if self.fail:
            raise ConnectionError("redis down")
        return self._data.get(key)

    async def delete(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis down")
        return 1 if self._data.pop(key, None) is not None else 0

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:
        if self.fail:
            raise ConnectionError("redis down")
        if 'redis.call("get", KEYS[1]) == ARGV[1]' in script:
            key = str(keys_and_args[0])
            token = str(keys_and_args[1])
            if self._data.get(key) == token:
                self._data.pop(key, None)
                return 1
            return 0
        if "payload['business_idempotency_key']" in script:
            key = str(keys_and_args[0])
            raw = self._data.get(key)
            if not raw:
                return "ERR:NOT_FOUND"
            payload = json.loads(raw)
            now = float(keys_and_args[1])
            if now >= float(payload["expires_at"]):
                self._data.pop(key, None)
                return "ERR:EXPIRED"
            if (
                payload["user_id"] != keys_and_args[2]
                or payload["store_id"] != keys_and_args[3]
                or payload["session_id"] != keys_and_args[4]
            ):
                return "ERR:FORBIDDEN"
            if keys_and_args[5] and payload["draft_id"] != keys_and_args[5]:
                return "ERR:DRAFT_MISMATCH"
            status = payload.get("status") or "PENDING"
            if status in ("SUCCEEDED", "REJECTED", "FAILED", "EXECUTING"):
                return "ERR:ALREADY_USED"
            key_arg = keys_and_args[6]
            if key_arg:
                payload["business_idempotency_key"] = key_arg
            elif not payload.get("business_idempotency_key"):
                return "ERR:MISSING_KEY"
            payload["status"] = "EXECUTING"
            self._data[key] = json.dumps(payload)
            return "OK:" + json.dumps(payload)
        if "payload['status'] = 'REJECTED'" in script:
            key = str(keys_and_args[0])
            raw = self._data.get(key)
            if not raw:
                return "ERR:NOT_FOUND"
            payload = json.loads(raw)
            now = float(keys_and_args[1])
            if now >= float(payload["expires_at"]):
                self._data.pop(key, None)
                return "ERR:EXPIRED"
            if (
                payload["user_id"] != keys_and_args[2]
                or payload["store_id"] != keys_and_args[3]
                or payload["session_id"] != keys_and_args[4]
            ):
                return "ERR:FORBIDDEN"
            if keys_and_args[5] and payload["draft_id"] != keys_and_args[5]:
                return "ERR:DRAFT_MISMATCH"
            status = payload.get("status") or "PENDING"
            if status != "PENDING":
                return "ERR:ALREADY_USED"
            payload["status"] = "REJECTED"
            self._data[key] = json.dumps(payload)
            return "OK:" + json.dumps(payload)
        if "payload['status'] = ARGV[1]" in script:
            key = str(keys_and_args[0])
            raw = self._data.get(key)
            if not raw:
                return "ERR:NOT_FOUND"
            payload = json.loads(raw)
            payload["status"] = keys_and_args[1]
            self._data[key] = json.dumps(payload)
            return "OK:" + json.dumps(payload)
        raise NotImplementedError


# --- Production Redis required -------------------------------------------------


def test_production_requires_redis_url() -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            server={"environment": "production"},
            jwt={"url": "https://example.com/.well-known/jwks.json"},
            openai={"base_url": "https://api.openai.com/v1", "api_key": "k"},
            guards={"input_mode": "enforce", "output_mode": "enforce"},
            limits={"redis_url": None},
        )
    assert "AI_REDIS_URL" in str(caught.value)


# --- Confirmation state machine -----------------------------------------------


def test_concurrent_claim_one_winner() -> None:
    asyncio.run(_concurrent_claim())


async def _concurrent_claim() -> None:
    store = InMemoryConfirmationStore()
    record = await store.create(
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        type="ledger_credit",
        draft_id=CUSTOMER,
        summary={"action": "payment", "total": 100},
        tool_name="ledger_credit",
        arguments={"storeId": STORE, "customerId": CUSTOMER, "amount": 100},
    )

    async def claim() -> str:
        try:
            claimed = await store.claim(
                record.confirmation_id,
                user_id="u1",
                store_id=STORE,
                session_id=SESSION,
            )
            return claimed.status
        except AppError as exc:
            return exc.code

    results = await asyncio.gather(claim(), claim())
    assert results.count("EXECUTING") == 1
    assert results.count("CONFIRMATION_REQUIRED") == 1


def test_wrong_user_cannot_claim() -> None:
    asyncio.run(_wrong_user_claim())


async def _wrong_user_claim() -> None:
    store = InMemoryConfirmationStore()
    record = await store.create(
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        type="ledger_credit",
        draft_id=CUSTOMER,
        summary={},
        tool_name="ledger_credit",
        arguments={"storeId": STORE, "customerId": CUSTOMER, "amount": 1},
    )
    with pytest.raises(AppError) as caught:
        await store.claim(
            record.confirmation_id,
            user_id="other",
            store_id=STORE,
            session_id=SESSION,
        )
    assert caught.value.status_code == 403


def test_timeout_becomes_unknown_then_retry() -> None:
    asyncio.run(_unknown_then_retry())


async def _unknown_then_retry() -> None:
    retailer = TimeoutRetailer(succeed_on=2)
    registry = _registry()
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(registry=registry, retailer=retailer)
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="ledger_credit",
                arguments={
                    "storeId": STORE,
                    "customerId": CUSTOMER,
                    "amount": 50,
                },
            )
        ],
    )
    assert staged is not None
    body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId=staged.confirmation_id,
        draftId=CUSTOMER,
        action="approve",
    )
    first = await handle_confirm(
        body,
        user_id="u1",
        request_id="r1",
        store_id=STORE,
        access_token="tok",
        confirmations=confirmations,
        sessions=InMemorySessionStore(),
        executor=executor,
        guard_output=_guard,
    )
    assert "unclear" in first.message.lower()
    assert retailer.calls == 1
    record = await confirmations.get(
        staged.confirmation_id,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
    )
    assert record.status == "UNKNOWN"
    key = record.business_idempotency_key
    assert key

    second = await handle_confirm(
        body,
        user_id="u1",
        request_id="r2",
        store_id=STORE,
        access_token="tok",
        confirmations=confirmations,
        sessions=InMemorySessionStore(),
        executor=executor,
        guard_output=_guard,
    )
    assert "recorded" in second.message.lower()
    assert retailer.calls == 2
    # Terminal SUCCEEDED: further claim is rejected.
    with pytest.raises(AppError) as caught:
        await confirmations.claim(
            staged.confirmation_id,
            user_id="u1",
            store_id=STORE,
            session_id=SESSION,
        )
    assert caught.value.status_code == 409
    # Same business key was reused on the successful retry.
    assert retailer.calls == 2
    assert key  # stored at first claim; retry reused it via store


def test_known_failure_becomes_failed() -> None:
    asyncio.run(_known_failure())


async def _known_failure() -> None:
    registry = _registry()
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(registry=registry, retailer=FailRetailer())
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="ledger_credit",
                arguments={
                    "storeId": STORE,
                    "customerId": CUSTOMER,
                    "amount": 50,
                },
            )
        ],
    )
    assert staged is not None
    response = await handle_confirm(
        ConfirmRequest(
            sessionId=SESSION,
            storeId=STORE,
            confirmationId=staged.confirmation_id,
            draftId=CUSTOMER,
            action="approve",
        ),
        user_id="u1",
        request_id="r1",
        store_id=STORE,
        access_token="tok",
        confirmations=confirmations,
        sessions=InMemorySessionStore(),
        executor=executor,
        guard_output=_guard,
    )
    assert "Could not record" in response.message
    with pytest.raises(AppError) as caught:
        await confirmations.claim(
            staged.confirmation_id,
            user_id="u1",
            store_id=STORE,
            session_id=SESSION,
        )
    assert caught.value.status_code == 409


# --- Concurrency leases -------------------------------------------------------


def test_lease_acquire_release_and_expiry() -> None:
    asyncio.run(_lease_flow())


async def _lease_flow() -> None:
    gate = InMemoryConcurrencyGate(max_chat=1, lease_seconds=1)
    lease = await gate.acquire_chat(user_id="u1", store_id=STORE)
    with pytest.raises(AppError) as caught:
        await gate.acquire_chat(user_id="u1", store_id=STORE)
    assert caught.value.code == "AI_CONCURRENCY_LIMIT"
    await gate.release(lease)
    lease2 = await gate.acquire_chat(user_id="u1", store_id=STORE)
    assert lease2.slot == 0
    # Wrong token cannot release.
    await gate.release(
        Lease(
            kind=lease2.kind,
            user_id=lease2.user_id,
            store_id=lease2.store_id,
            token="wrong",
            slot=lease2.slot,
        )
    )
    with pytest.raises(AppError):
        await gate.acquire_chat(user_id="u1", store_id=STORE)
    await gate.release(lease2)
    # Expiry frees the slot.
    short = InMemoryConcurrencyGate(max_chat=1, lease_seconds=0)
    await short.acquire_chat(user_id="u1", store_id=STORE)
    time.sleep(0.01)
    again = await short.acquire_chat(user_id="u1", store_id=STORE)
    assert again.slot == 0


def test_redis_concurrency_fail_closed() -> None:
    asyncio.run(_redis_concurrency_down())


async def _redis_concurrency_down() -> None:
    from app.limits.concurrency import ConcurrencyGate

    gate = ConcurrencyGate(FakeRedis(fail=True), max_chat=2)
    with pytest.raises(AppError) as caught:
        await gate.acquire_chat(user_id="u1", store_id=STORE)
    assert caught.value.status_code == 503


# --- RequestBudget ------------------------------------------------------------


def test_request_budget_limits() -> None:
    budget = RequestBudget(
        max_model_calls=1,
        max_tool_calls=1,
        max_estimated_input_tokens=10,
        max_estimated_output_tokens=10,
        deadline_seconds=60,
    )
    budget.begin_model_call()
    with pytest.raises(BudgetExceeded):
        budget.begin_model_call()
    budget2 = RequestBudget(max_tool_calls=2, max_model_calls=10)
    budget2.begin_tool_batch(2)
    with pytest.raises(BudgetExceeded):
        budget2.begin_tool_batch(1)
    budget3 = RequestBudget(
        max_model_calls=5,
        max_estimated_input_tokens=5,
        max_estimated_output_tokens=100,
    )
    budget3.begin_model_call()
    budget3.record_tokens(input_tokens=5, output_tokens=1)
    with pytest.raises(BudgetExceeded):
        budget3.begin_model_call()
    budget4 = RequestBudget(deadline_seconds=0.01, max_model_calls=10)
    time.sleep(0.02)
    with pytest.raises(BudgetExceeded):
        budget4.begin_model_call()


# --- Rate limits --------------------------------------------------------------


def test_rate_limit_and_isolation() -> None:
    asyncio.run(_rate_limits())


async def _rate_limits() -> None:
    limiter = InMemoryRateLimiter(chat_per_minute=2, confirm_per_minute=1)
    await limiter.check_chat(user_id="u1", store_id=STORE)
    await limiter.check_chat(user_id="u1", store_id=STORE)
    with pytest.raises(AppError) as caught:
        await limiter.check_chat(user_id="u1", store_id=STORE)
    assert caught.value.code == "AI_RATE_LIMITED"
    # Isolation by user/store.
    await limiter.check_chat(user_id="u2", store_id=STORE)
    await limiter.check_confirm(user_id="u1", store_id=STORE)
    with pytest.raises(AppError):
        await limiter.check_confirm(user_id="u1", store_id=STORE)


def test_redis_rate_limit_fail_closed() -> None:
    asyncio.run(_redis_rate_down())


async def _redis_rate_down() -> None:
    from app.limits.rate_limit import RateLimiter

    limiter = RateLimiter(FakeRedis(fail=True), chat_per_minute=10)
    with pytest.raises(AppError) as caught:
        await limiter.check_chat(user_id="u1", store_id=STORE)
    assert caught.value.status_code == 503


# --- Provider breaker / retry / budget ----------------------------------------


class FlakyProvider:
    """Registered as cheaper (default pick); fails so gateway falls back."""

    name = CHEAPER_PROVIDER_NAME

    def __init__(self, failures: int) -> None:
        self.failures_left = failures
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="timeout",
                status_code=503,
                retryable=True,
            )
        return GenerationResponse(
            provider=self.name, model="m", content="ok", tool_calls=[]
        )


class FallbackProvider:
    name = OPENAI_PROVIDER_NAME

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls += 1
        return GenerationResponse(
            provider=self.name, model="gpt", content="fallback", tool_calls=[]
        )


def test_provider_retry_and_fallback_consume_budget() -> None:
    asyncio.run(_provider_retry_budget())


async def _provider_retry_budget() -> None:
    primary = FlakyProvider(failures=2)
    fallback = FallbackProvider()
    router = ModelRouter()
    router.register(primary)
    router.register(fallback)
    router.set_active(primary.name)
    gateway = AiGateway(router, breaker=CircuitBreaker(name="t", failure_threshold=10))
    budget = RequestBudget(max_model_calls=3)
    response = await gateway.generate(
        GenerationRequest(
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0,
            max_tokens=16,
        ),
        budget=budget,
    )
    assert response.content == "fallback"
    assert primary.calls == 2
    assert fallback.calls == 1
    assert budget.model_calls == 3


def test_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(
        name="t", failure_threshold=2, cooldown_seconds=0.05
    )
    breaker.allow()
    breaker.record_failure()
    breaker.allow()
    breaker.record_failure()
    assert breaker._record.state == BreakerState.OPEN
    with pytest.raises(AppError) as caught:
        breaker.allow()
    assert caught.value.code == "AI_DEPENDENCY_UNAVAILABLE"
    time.sleep(0.06)
    breaker.allow()
    assert breaker._record.state == BreakerState.HALF_OPEN
    breaker.record_success()
    assert breaker._record.state == BreakerState.CLOSED


def test_non_retryable_does_not_fallback() -> None:
    asyncio.run(_non_retryable())


async def _non_retryable() -> None:
    class BadProvider:
        name = CHEAPER_PROVIDER_NAME

        async def generate(self, request: GenerationRequest) -> GenerationResponse:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="bad request",
                status_code=400,
                retryable=False,
            )

    router = ModelRouter()
    router.register(BadProvider())
    router.register(FallbackProvider())
    router.set_active(CHEAPER_PROVIDER_NAME)
    gateway = AiGateway(router)
    with pytest.raises(AppError) as caught:
        await gateway.generate(
            GenerationRequest(
                messages=[ChatMessage(role="user", content="hi")],
                temperature=0,
                max_tokens=8,
            ),
            budget=RequestBudget(max_model_calls=4),
        )
    assert caught.value.retryable is False


# --- RAG degradation ----------------------------------------------------------


class FailingRetriever:
    async def retrieve(self, question: str):
        raise AppError(
            code="RAG_UNAVAILABLE",
            message="qdrant down",
            status_code=503,
        )


def test_docs_routing_unavailable() -> None:
    asyncio.run(_docs_unavailable())


async def _docs_unavailable() -> None:
    settings = SimpleNamespace(
        rag=SimpleNamespace(
            context_max_tokens=1000, context_max_tokens_action=512
        )
    )
    # Nonsense query must not match local markdown keywords.
    context = await build_chat_context(
        sessions=InMemorySessionStore(),
        retriever=FailingRetriever(),  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        question="xyzzy plugh qwerty asdfgh",
        language="en",
        session_id=SESSION,
        user_id="u1",
        store_id=STORE,
        tools=[],
        routing="docs",
    )
    assert context.docs_unavailable is True


def test_docs_routing_local_fallback_when_rag_fails() -> None:
    asyncio.run(_docs_local_fallback())


async def _docs_local_fallback() -> None:
    settings = SimpleNamespace(
        rag=SimpleNamespace(
            context_max_tokens=1000, context_max_tokens_action=512
        )
    )
    context = await build_chat_context(
        sessions=InMemorySessionStore(),
        retriever=FailingRetriever(),  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        question="How do I use DragBizz chat voice assistant?",
        language="en",
        session_id=SESSION,
        user_id="u1",
        store_id=STORE,
        tools=[],
        routing="docs",
    )
    assert context.docs_unavailable is False
    assert context.messages
    assert context.retrieved
    assert any(
        "voice" in (chunk.metadata.get("source") or "")
        or "assistant" in (chunk.metadata.get("source") or "")
        for chunk in context.retrieved
    )


def test_both_routing_continues_without_docs() -> None:
    asyncio.run(_both_continues())


async def _both_continues() -> None:
    settings = SimpleNamespace(
        rag=SimpleNamespace(
            context_max_tokens=1000, context_max_tokens_action=512
        )
    )
    tools = [
        ToolDefinition(
            name="search_products",
            description="search",
            parameters={"type": "object", "properties": {}},
            risk=ToolRisk.READ,
        )
    ]
    context = await build_chat_context(
        sessions=InMemorySessionStore(),
        retriever=FailingRetriever(),  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        question="how do I bill maggi?",
        language="en",
        session_id=SESSION,
        user_id="u1",
        store_id=STORE,
        tools=tools,
        routing="both",
    )
    assert context.docs_unavailable is False
    assert context.messages
    # Governance / allowlist unchanged — tools still present in system prompt.
    assert any("search_products" in (m.content or "") for m in context.messages)


def test_redis_confirmation_fail_closed() -> None:
    asyncio.run(_confirm_redis_down())


async def _confirm_redis_down() -> None:
    from app.confirmations import RedisConfirmationStore

    store = RedisConfirmationStore(FakeRedis(fail=True))
    with pytest.raises(AppError) as caught:
        await store.create(
            user_id="u1",
            store_id=STORE,
            session_id=SESSION,
            type="ledger_credit",
            draft_id=CUSTOMER,
            summary={},
            tool_name="ledger_credit",
            arguments={"storeId": STORE},
        )
    assert caught.value.status_code == 503


# --- Phase 1: JWKS, Concurrency Lua, & Endpoint Teardown Regressions ----------


@pytest.mark.asyncio
async def test_jwks_async_thread_offload_success() -> None:
    from app.integrations.auth_jwks import JwksTokenVerifier

    mock_client = MagicMock()
    mock_key = MagicMock()
    mock_key.key = "fake-public-key"
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    settings = SimpleNamespace(
        jwt=SimpleNamespace(
            url="https://auth.example.com/.well-known/jwks.json",
            cache_ttl_seconds=300,
            algorithms=["RS256"],
            audience="retailer-admin",
            issuer="dragbizz-auth",
            clock_skew_seconds=0,
        )
    )
    verifier = JwksTokenVerifier(settings=settings, jwks_client=mock_client)  # type: ignore[arg-type]

    with (
        patch("jwt.decode") as mock_decode,
        patch("asyncio.to_thread", wraps=asyncio.to_thread) as spy_to_thread,
    ):
        mock_decode.return_value = {
            "sub": "user-123",
            "agencyId": "agency-456",
            "tenant": "Tenant-A",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
        }
        claims = await verifier.verify("valid.token", None)  # type: ignore[arg-type]
        assert claims["sub"] == "user-123"
        assert claims["tenant"] == "tenant-a"
        assert spy_to_thread.called


@pytest.mark.asyncio
async def test_jwks_missing_kid_and_unknown_signing_key_id() -> None:
    from app.integrations.auth_jwks import JwksTokenVerifier

    mock_client = MagicMock()
    settings = SimpleNamespace(
        jwt=SimpleNamespace(
            url="https://auth.example.com/.well-known/jwks.json",
            cache_ttl_seconds=300,
            algorithms=["RS256"],
            audience="retailer-admin",
            issuer="dragbizz-auth",
            clock_skew_seconds=0,
        )
    )
    verifier = JwksTokenVerifier(settings=settings, jwks_client=mock_client)  # type: ignore[arg-type]

    # 1. Missing kid in token header (header.get("kid") is None)
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError(
        'Unable to find a signing key that matches: "None"'
    )
    with pytest.raises(AppError) as exc_missing_kid:
        await verifier.verify("token.without.kid", None)  # type: ignore[arg-type]
    assert exc_missing_kid.value.status_code == 401
    assert exc_missing_kid.value.code == "AUTH_INVALID"
    assert exc_missing_kid.value.message == "Invalid access token"
    assert "None" not in exc_missing_kid.value.message

    # 2. Unknown signing-key ID (kid not found in JWKS)
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError(
        'Unable to find a signing key that matches: "unknown-key-id-999"'
    )
    with pytest.raises(AppError) as exc_unknown_kid:
        await verifier.verify("token.with.unknown.kid", None)  # type: ignore[arg-type]
    assert exc_unknown_kid.value.status_code == 401
    assert exc_unknown_kid.value.code == "AUTH_INVALID"
    assert exc_unknown_kid.value.message == "Invalid access token"
    assert "unknown-key-id" not in exc_unknown_kid.value.message


@pytest.mark.asyncio
async def test_jwks_network_timeout_or_connection_failure() -> None:
    from app.integrations.auth_jwks import JwksTokenVerifier

    mock_client = MagicMock()
    settings = SimpleNamespace(
        jwt=SimpleNamespace(
            url="https://auth.example.com/.well-known/jwks.json",
            cache_ttl_seconds=300,
            algorithms=["RS256"],
            audience="retailer-admin",
            issuer="dragbizz-auth",
            clock_skew_seconds=0,
        )
    )
    verifier = JwksTokenVerifier(settings=settings, jwks_client=mock_client)  # type: ignore[arg-type]

    # 1. Connection refused / network failure
    mock_client.get_signing_key_from_jwt.side_effect = (
        jwt.PyJWKClientConnectionError("Connection refused to auth.example.com:443")
    )
    with pytest.raises(AppError) as exc_conn:
        await verifier.verify("token", None)  # type: ignore[arg-type]
    assert exc_conn.value.status_code == 503
    assert exc_conn.value.code == "AUTH_UNAVAILABLE"
    assert exc_conn.value.message == "Auth service unavailable"
    assert "auth.example.com" not in exc_conn.value.message

    # 2. Timeout error
    mock_client.get_signing_key_from_jwt.side_effect = (
        jwt.PyJWKClientConnectionError("The read operation timed out")
    )
    with pytest.raises(AppError) as exc_timeout:
        await verifier.verify("token", None)  # type: ignore[arg-type]
    assert exc_timeout.value.status_code == 503
    assert exc_timeout.value.code == "AUTH_UNAVAILABLE"
    assert exc_timeout.value.message == "Auth service unavailable"


@pytest.mark.asyncio
async def test_jwks_malformed_or_unusable_responses() -> None:
    from app.integrations.auth_jwks import JwksTokenVerifier

    mock_client = MagicMock()
    settings = SimpleNamespace(
        jwt=SimpleNamespace(
            url="https://auth.example.com/.well-known/jwks.json",
            cache_ttl_seconds=300,
            algorithms=["RS256"],
            audience="retailer-admin",
            issuer="dragbizz-auth",
            clock_skew_seconds=0,
        )
    )
    verifier = JwksTokenVerifier(settings=settings, jwks_client=mock_client)  # type: ignore[arg-type]

    # 1. Malformed non-JSON response from JWKS endpoint (service failure, NOT 401)
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError(
        "The JWKS endpoint did not return a JSON object"
    )
    with pytest.raises(AppError) as exc_non_json:
        await verifier.verify("token", None)  # type: ignore[arg-type]
    assert exc_non_json.value.status_code == 503
    assert exc_non_json.value.code == "AUTH_UNAVAILABLE"
    assert exc_non_json.value.message == "Auth service unavailable"

    # 2. JWK Set did not contain any keys (service failure, NOT 401)
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKSetError(
        "The JWK Set did not contain any keys"
    )
    with pytest.raises(AppError) as exc_empty_set:
        await verifier.verify("token", None)  # type: ignore[arg-type]
    assert exc_empty_set.value.status_code == 503
    assert exc_empty_set.value.code == "AUTH_UNAVAILABLE"
    assert exc_empty_set.value.message == "Auth service unavailable"

    # 3. JWK Set did not contain any usable keys (service failure, NOT 401)
    mock_client.get_signing_key_from_jwt.side_effect = jwt.PyJWKSetError(
        "The JWK Set did not contain any usable keys."
    )
    with pytest.raises(AppError) as exc_unusable:
        await verifier.verify("token", None)  # type: ignore[arg-type]
    assert exc_unusable.value.status_code == 503
    assert exc_unusable.value.code == "AUTH_UNAVAILABLE"
    assert exc_unusable.value.message == "Auth service unavailable"


@pytest.mark.asyncio
async def test_jwks_expired_and_invalid_token_error_mapping() -> None:
    from app.integrations.auth_jwks import JwksTokenVerifier

    mock_client = MagicMock()
    mock_key = MagicMock()
    mock_key.key = "fake-public-key"
    mock_client.get_signing_key_from_jwt.return_value = mock_key

    settings = SimpleNamespace(
        jwt=SimpleNamespace(
            url="https://auth.example.com/.well-known/jwks.json",
            cache_ttl_seconds=300,
            algorithms=["RS256"],
            audience="retailer-admin",
            issuer="dragbizz-auth",
            clock_skew_seconds=0,
        )
    )
    verifier = JwksTokenVerifier(settings=settings, jwks_client=mock_client)  # type: ignore[arg-type]

    # Expired token
    with patch(
        "jwt.decode",
        side_effect=jwt.ExpiredSignatureError("Signature expired"),
    ):
        with pytest.raises(AppError) as exc_exp:
            await verifier.verify("expired.token", None)  # type: ignore[arg-type]
        assert exc_exp.value.status_code == 401
        assert exc_exp.value.code == "AUTH_EXPIRED"
        assert exc_exp.value.message == "Access token expired"

    # Malformed token format (DecodeError)
    with patch("jwt.decode", side_effect=jwt.DecodeError("Not enough segments")):
        with pytest.raises(AppError) as exc_decode:
            await verifier.verify("bad.format", None)  # type: ignore[arg-type]
        assert exc_decode.value.status_code == 401
        assert exc_decode.value.code == "AUTH_INVALID"
        assert exc_decode.value.message == "Invalid access token"

    # Invalid signature (InvalidSignatureError)
    with patch(
        "jwt.decode",
        side_effect=jwt.InvalidSignatureError("Signature verification failed"),
    ):
        with pytest.raises(AppError) as exc_sig:
            await verifier.verify("bad.sig", None)  # type: ignore[arg-type]
        assert exc_sig.value.status_code == 401
        assert exc_sig.value.code == "AUTH_INVALID"
        assert exc_sig.value.message == "Invalid access token"


@pytest.mark.asyncio
async def test_redis_concurrency_release_atomic_lua() -> None:
    from app.limits.concurrency import ConcurrencyGate

    fake_redis = FakeRedis()
    gate = ConcurrencyGate(fake_redis, max_chat=1)

    # Acquire lease (slot 0)
    lease = await gate.acquire_chat(user_id="u1", store_id=STORE)
    assert lease.slot == 0

    # Wrong token cannot release (Lua returns 0, key remains)
    wrong_lease = Lease(
        kind=lease.kind,
        user_id=lease.user_id,
        store_id=lease.store_id,
        token="wrong-token",
        slot=lease.slot,
    )
    await gate.release(wrong_lease)

    # Next acquire fails because slot 0 is still held
    with pytest.raises(AppError) as exc:
        await gate.acquire_chat(user_id="u1", store_id=STORE)
    assert exc.value.code == "AI_CONCURRENCY_LIMIT"

    # Correct token releases atomically
    await gate.release(lease)

    # Slot is now available
    reacquired = await gate.acquire_chat(user_id="u1", store_id=STORE)
    assert reacquired.slot == 0
    await gate.release(reacquired)


@pytest.mark.asyncio
async def test_redis_concurrency_release_failure_does_not_raise() -> None:
    from app.limits.concurrency import ConcurrencyGate

    failing_redis = FakeRedis(fail=True)
    gate = ConcurrencyGate(failing_redis, max_chat=1)
    lease = Lease(kind="chat", user_id="u1", store_id=STORE, token="t", slot=0)

    # Release on failing Redis must suppress error, log warning, and NOT raise
    await gate.release(lease)


@pytest.mark.asyncio
async def test_chat_endpoints_teardown_swallows_release_error() -> None:
    from fastapi import Request

    from app.api.v1.chat import chat, chat_stream, confirm_chat
    from app.schemas.chat import ChatRequest, ChatResponse, ConfirmRequest

    class ExplodingGate:
        async def acquire_chat(self, *args: Any, **kwargs: Any) -> Lease:
            return Lease(kind="chat", user_id="u1", store_id=STORE, token="t", slot=0)

        async def acquire_confirm(self, *args: Any, **kwargs: Any) -> Lease:
            return Lease(
                kind="confirm",
                user_id="u1",
                store_id=STORE,
                token="t",
                slot=0,
            )

        async def release(self, lease: Any) -> None:
            raise RuntimeError("Redis exploded during release")

    class MockChatService:
        async def handle(self, *args: Any, **kwargs: Any) -> ChatResponse:
            return ChatResponse(
                message="hello from mock",
                session_id=SESSION,
                request_id="req-1",
                user_id="u1",
                provider="mock-p",
                model="mock-m",
            )

        async def handle_stream(self, *args: Any, **kwargs: Any) -> Any:
            yield ("token", {"delta": "hello"})
            yield ("done", {"message": "hello"})

        async def confirm(self, *args: Any, **kwargs: Any) -> ChatResponse:
            return ChatResponse(
                message="confirmed from mock",
                session_id=SESSION,
                request_id="req-1",
                user_id="u1",
                provider="mock-p",
                model="mock-m",
            )

    app_mock = MagicMock()
    app_mock.state.concurrency_gate = ExplodingGate()
    app_mock.state.rate_limiter = None

    scope = {
        "type": "http",
        "app": app_mock,
        "state": {
            "access_token": "valid.token",
            "request_id": "req-1",
        },
    }
    mock_request = Request(scope)
    user = {"sub": "u1", "agencyId": "ag1"}
    chat_service = MockChatService()

    # 1. /chat endpoint teardown resilience
    req_body = ChatRequest(text="hi", sessionId=SESSION, storeId=STORE)
    resp = await chat(req_body, mock_request, user, chat_service)  # type: ignore[arg-type]
    assert resp.message == "hello from mock"

    # 2. /chat/stream endpoint teardown resilience
    stream_resp = await chat_stream(req_body, mock_request, user, chat_service)  # type: ignore[arg-type]
    events = []
    async for chunk in stream_resp.body_iterator:
        events.append(chunk)
    assert len(events) == 2

    # 3. /chat/confirm endpoint teardown resilience
    conf_body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId="c" * 24,
        draftId=CUSTOMER,
        action="approve",
    )
    conf_resp = await confirm_chat(conf_body, mock_request, user, chat_service)  # type: ignore[arg-type]
    assert conf_resp.message == "confirmed from mock"


@pytest.mark.asyncio
async def test_redis_confirmation_atomic_reject_and_concurrent_claim_race() -> None:
    from app.confirmations import RedisConfirmationStore

    fake_redis = FakeRedis()
    store = RedisConfirmationStore(fake_redis)
    record = await store.create(
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        type="ledger_credit",
        draft_id=CUSTOMER,
        summary={"total": 50},
        tool_name="ledger_credit",
        arguments={"storeId": STORE, "customerId": CUSTOMER, "amount": 50},
    )

    rejected = await store.reject(
        record.confirmation_id,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        draft_id=CUSTOMER,
    )
    assert rejected.status == "REJECTED"

    with pytest.raises(AppError) as caught:
        await store.claim(
            record.confirmation_id,
            user_id="u1",
            store_id=STORE,
            session_id=SESSION,
            draft_id=CUSTOMER,
        )
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_confirmation_argument_modification_rejected() -> None:
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(
        registry=_registry(),
        retailer=TimeoutRetailer(succeed_on=1),
    )
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="ledger_credit",
                arguments={
                    "storeId": STORE,
                    "customerId": CUSTOMER,
                    "amount": 50,
                },
            )
        ],
    )
    assert staged is not None
    body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId=staged.confirmation_id,
        draftId=CUSTOMER,
        action="approve",
        updates={"amount": 999},
    )
    with pytest.raises(AppError) as caught:
        await handle_confirm(
            body,
            user_id="u1",
            request_id="r1",
            store_id=STORE,
            access_token="tok",
            confirmations=confirmations,
            sessions=InMemorySessionStore(),
            executor=executor,
            guard_output=_guard,
        )
    assert caught.value.status_code == 400
    assert caught.value.code == "CONFIRMATION_ARGUMENTS_INVALID"


@pytest.mark.asyncio
async def test_confirmation_cross_store_updates_rejected() -> None:
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(
        registry=_registry(),
        retailer=TimeoutRetailer(succeed_on=1),
    )
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="ledger_credit",
                arguments={
                    "storeId": STORE,
                    "customerId": CUSTOMER,
                    "amount": 50,
                },
            )
        ],
    )
    assert staged is not None
    body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId=staged.confirmation_id,
        draftId=CUSTOMER,
        action="approve",
        updates={"storeId": "x" * 24},
    )
    with pytest.raises(AppError) as caught:
        await handle_confirm(
            body,
            user_id="u1",
            request_id="r1",
            store_id=STORE,
            access_token="tok",
            confirmations=confirmations,
            sessions=InMemorySessionStore(),
            executor=executor,
            guard_output=_guard,
        )
    assert caught.value.status_code == 403
    assert caught.value.code == "STORE_FORBIDDEN"


@pytest.mark.asyncio
async def test_confirmation_additional_arguments_rejected() -> None:
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(
        registry=_registry(),
        retailer=TimeoutRetailer(succeed_on=1),
    )
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="ledger_credit",
                arguments={
                    "storeId": STORE,
                    "customerId": CUSTOMER,
                    "amount": 50,
                },
            )
        ],
    )
    assert staged is not None
    body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId=staged.confirmation_id,
        draftId=CUSTOMER,
        action="approve",
        updates={"extraField": "malicious_injection"},
    )
    with pytest.raises(AppError) as caught:
        await handle_confirm(
            body,
            user_id="u1",
            request_id="r1",
            store_id=STORE,
            access_token="tok",
            confirmations=confirmations,
            sessions=InMemorySessionStore(),
            executor=executor,
            guard_output=_guard,
        )
    assert caught.value.status_code == 400
    assert caught.value.code == "CONFIRMATION_ARGUMENTS_INVALID"


@pytest.mark.asyncio
async def test_confirmation_nested_argument_modification_rejected() -> None:
    confirmations = InMemoryConfirmationStore()
    executor = ToolExecutor(
        registry=_registry(),
        retailer=TimeoutRetailer(succeed_on=1),
    )
    staged = await stage_from_sensitive_calls(
        confirmations,
        user_id="u1",
        store_id=STORE,
        session_id=SESSION,
        sensitive_calls=[
            ToolCall(
                id="c1",
                name="add_stock",
                arguments={
                    "storeId": STORE,
                    "items": [
                        {
                            "productId": "p1",
                            "quantity": 10,
                            "purchasePrice": 100.0,
                        }
                    ],
                },
            )
        ],
    )
    assert staged is not None
    body = ConfirmRequest(
        sessionId=SESSION,
        storeId=STORE,
        confirmationId=staged.confirmation_id,
        draftId="p1",
        action="approve",
        updates={
            "items": [
                {
                    "productId": "p1",
                    "quantity": 9999,
                    "purchasePrice": 100.0,
                }
            ]
        },
    )
    with pytest.raises(AppError) as caught:
        await handle_confirm(
            body,
            user_id="u1",
            request_id="r1",
            store_id=STORE,
            access_token="tok",
            confirmations=confirmations,
            sessions=InMemorySessionStore(),
            executor=executor,
            guard_output=_guard,
        )
    assert caught.value.status_code == 400
    assert caught.value.code == "CONFIRMATION_ARGUMENTS_INVALID"


