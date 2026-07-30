"""B2 — session / multi-turn memory."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolResult
from app.sessions import InMemorySessionStore, SessionTurn, turns_to_messages
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"
OTHER_STORE = "507f1f77bcf86cd799439012"


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CapturingProvider(ModelProvider):
    def __init__(self, responses: list[GenerationResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "capturing"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return self._responses.pop(0)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register(definition, READ_TOOL_HANDLERS[definition.name])
    return registry


def _service(
    provider: ModelProvider,
    *,
    session_store: InMemorySessionStore,
) -> ChatService:
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = _registry()
    executor = MagicMock(spec=ToolExecutor)
    executor.execute_reads = AsyncMock(return_value=[])
    return ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test", output_guard_mode="off"),
        tool_executor=executor,
        session_store=session_store,
    )


def _handle(
    service: ChatService,
    *,
    text: str,
    session_id: str = "s1",
    user_id: str = "u1",
    store_id: str = STORE_ID,
) -> Any:
    return asyncio.run(
        service.handle(
            ChatRequest(
                text=text,
                sessionId=session_id,
                storeId=store_id,
                language="hi-IN",
            ),
            user={"sub": user_id},
            request_id="r1",
            store_id=store_id,
            access_token="token",
        )
    )


# -------------------------------------------------------------- store unit


def test_session_rejects_cross_user_reuse() -> None:
    store = InMemorySessionStore(ttl_seconds=60)

    async def run() -> None:
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(user_text="hi", assistant_text="hello"),
        )
        with pytest.raises(AppError) as exc:
            await store.load_history(
                session_id="s1", user_id="u2", store_id=STORE_ID
            )
        assert exc.value.code == "SESSION_FORBIDDEN"
        assert exc.value.status_code == 403

    asyncio.run(run())


def test_session_rejects_cross_store_reuse() -> None:
    store = InMemorySessionStore(ttl_seconds=60)

    async def run() -> None:
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(user_text="hi", assistant_text="hello"),
        )
        with pytest.raises(AppError) as exc:
            await store.append_turn(
                session_id="s1",
                user_id="u1",
                store_id=OTHER_STORE,
                turn=SessionTurn(user_text="again", assistant_text="nope"),
            )
        assert exc.value.code == "SESSION_FORBIDDEN"

    asyncio.run(run())


def test_session_ttl_expiry_clears_history() -> None:
    clock = _Clock()
    store = InMemorySessionStore(ttl_seconds=30, clock=clock)

    async def run() -> None:
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(user_text="q1", assistant_text="a1"),
        )
        clock.advance(29)
        history = await store.load_history(
            session_id="s1", user_id="u1", store_id=STORE_ID
        )
        assert len(history) == 1

        clock.advance(31)
        history = await store.load_history(
            session_id="s1", user_id="u1", store_id=STORE_ID
        )
        assert history == []

    asyncio.run(run())


def test_session_trims_to_max_turns() -> None:
    store = InMemorySessionStore(ttl_seconds=60, max_turns=2)

    async def run() -> None:
        for index in range(3):
            await store.append_turn(
                session_id="s1",
                user_id="u1",
                store_id=STORE_ID,
                turn=SessionTurn(
                    user_text=f"q{index}", assistant_text=f"a{index}"
                ),
            )
        history = await store.load_history(
            session_id="s1", user_id="u1", store_id=STORE_ID
        )
        assert [turn.user_text for turn in history] == ["q1", "q2"]

    asyncio.run(run())


def test_session_trims_by_history_max_tokens() -> None:
    store = InMemorySessionStore(
        ttl_seconds=60, max_turns=10, history_max_tokens=40
    )

    async def run() -> None:
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(
                user_text="old question " + ("x" * 80),
                assistant_text="old answer " + ("y" * 80),
            ),
        )
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(user_text="new q", assistant_text="new a"),
        )
        history = await store.load_history(
            session_id="s1", user_id="u1", store_id=STORE_ID
        )
        assert [turn.user_text for turn in history] == ["new q"]

    asyncio.run(run())


def test_session_drops_tool_context_on_older_turns() -> None:
    store = InMemorySessionStore(ttl_seconds=60, max_turns=5)

    async def run() -> None:
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(
                user_text="sale?",
                assistant_text="₹500",
                tool_context='[{"tool":"today_sale"}]',
            ),
        )
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(
                user_text="again?",
                assistant_text="ok",
                tool_context='[{"tool":"stock_summary"}]',
            ),
        )
        history = await store.load_history(
            session_id="s1", user_id="u1", store_id=STORE_ID
        )
        assert history[0].tool_context is None
        assert history[1].tool_context == '[{"tool":"stock_summary"}]'

    asyncio.run(run())


def test_turns_to_messages_includes_tool_context() -> None:
    messages = turns_to_messages(
        [
            SessionTurn(
                user_text="sale?",
                assistant_text="₹500",
                tool_context='[{"tool":"today_sale","success":true}]',
            )
        ]
    )
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert "[Prior tool results]" in messages[1].content
    assert "today_sale" in messages[1].content


# -------------------------------------------------------------- chat wiring


def test_follow_up_includes_prior_tool_context() -> None:
    store = InMemorySessionStore(ttl_seconds=600)
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing",
                model="m",
                content="Profit ₹100 tha.",
            ),
        ]
    )
    service = _service(provider, session_store=store)

    async def seed() -> None:
        await store.append_turn(
            session_id="s1",
            user_id="u1",
            store_id=STORE_ID,
            turn=SessionTurn(
                user_text="Aaj ki sale?",
                assistant_text="Aaj ki sale ₹500 hai.",
                tool_context=(
                    '[{"tool":"today_sale","success":true,'
                    '"data":{"revenue":500,"profit":100}}]'
                ),
            ),
        )

    asyncio.run(seed())

    response = _handle(service, text="Usme profit kitna tha?")
    assert response.session_id == "s1"
    assert response.message == "Profit ₹100 tha."
    assert len(provider.requests) == 1
    roles = [message.role for message in provider.requests[0].messages]
    assert roles == ["system", "user", "assistant", "user"]
    history_assistant = provider.requests[0].messages[2].content
    assert "500" in history_assistant
    assert "today_sale" in history_assistant
    assert provider.requests[0].messages[3].content == "Usme profit kitna tha?"


def test_chat_persists_turn_and_echoes_session_id() -> None:
    store = InMemorySessionStore(ttl_seconds=600)
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing",
                model="m",
                content="POS kholen.",
            )
        ]
    )
    response = _handle(_service(provider, session_store=store), text="POS kaise?")
    assert response.session_id == "s1"
    assert response.message == "POS kholen."

    history = asyncio.run(
        store.load_history(session_id="s1", user_id="u1", store_id=STORE_ID)
    )
    assert len(history) == 1
    assert history[0].user_text == "POS kaise?"
    assert history[0].assistant_text == "POS kholen."


def test_chat_cross_user_session_returns_403() -> None:
    store = InMemorySessionStore(ttl_seconds=600)
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing", model="m", content="ok"
            ),
            GenerationResponse(
                provider="capturing", model="m", content="should not run"
            ),
        ]
    )
    service = _service(provider, session_store=store)
    _handle(service, text="hello", user_id="u1")

    with pytest.raises(AppError) as exc:
        _handle(service, text="hijack", user_id="u2")
    assert exc.value.code == "SESSION_FORBIDDEN"


def test_chat_ttl_expiry_starts_fresh_session() -> None:
    clock = _Clock()
    store = InMemorySessionStore(ttl_seconds=10, clock=clock)
    provider = CapturingProvider(
        [
            GenerationResponse(
                provider="capturing", model="m", content="first"
            ),
            GenerationResponse(
                provider="capturing", model="m", content="second"
            ),
        ]
    )
    service = _service(provider, session_store=store)
    _handle(service, text="q1")
    clock.advance(11)
    response = _handle(service, text="q2")
    assert response.message == "second"
    # After expiry, second request should not include first turn in history.
    second_req = provider.requests[1]
    assert [m.role for m in second_req.messages] == ["system", "user"]
    assert second_req.messages[1].content == "q2"


def test_compact_tool_context_truncates() -> None:
    store = InMemorySessionStore(tool_context_max_chars=40)
    text = store.compact_tool_context(
        [
            ToolResult(
                tool="today_sale",
                success=True,
                data={"revenue": 1234567890, "note": "x" * 100},
            )
        ]
    )
    assert text is not None
    assert len(text) <= 40
    assert text.endswith("...")
