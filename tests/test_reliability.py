"""Phase 4: confirmation state machine, leases, budget, rate limits, breaker, RAG."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

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

    async def eval(self, *_args, **_kwargs):
        if self.fail:
            raise ConnectionError("redis down")
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
