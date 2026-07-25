from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.core.exceptions import AppError
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.prompts.system.chat import (
    build_chat_system_prompt,
    build_documentation_block,
)
from app.providers.base import ModelProvider
from app.rag.chunker import estimate_tokens
from app.rag.retriever import RetrievedChunk
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"


def _chunk(score: float, text: str, source: str) -> RetrievedChunk:
    return RetrievedChunk(text=text, metadata={"source": source}, score=score)


def test_system_prompt_without_documentation_has_no_placeholder() -> None:
    prompt = build_chat_system_prompt(
        language="en", store_id=STORE_ID, tools=[], documentation=""
    )
    assert "Documentation" not in prompt


def test_system_prompt_with_documentation_adds_block_and_rule() -> None:
    docs = build_documentation_block(
        [_chunk(0.9, "POS needs a paid plan.", "invoice/pos.md")], max_tokens=2000
    )
    prompt = build_chat_system_prompt(
        language="hi", store_id=STORE_ID, tools=[], documentation=docs
    )
    assert "Never answer live numbers from Documentation" in prompt
    assert "Documentation:\n[1] source=invoice/pos.md\nPOS needs a paid plan." in prompt
    assert "do not mention Tally unless the user asked" in prompt
    assert "[Tally](/dashboard/integrations/tally)" not in prompt


def test_documentation_block_cites_sources_in_score_order() -> None:
    block = build_documentation_block(
        [
            _chunk(0.9, "First doc.", "invoice/pos.md"),
            _chunk(0.7, "Second doc.", "customer/khata.md"),
        ],
        max_tokens=2000,
    )
    assert block.index("[1] source=invoice/pos.md") < block.index(
        "[2] source=customer/khata.md"
    )


def test_documentation_block_drops_lowest_score_chunks_over_budget() -> None:
    big_text = "word " * 400  # ~500 estimated tokens
    chunks = [
        _chunk(0.9, big_text, "a.md"),
        _chunk(0.8, big_text, "b.md"),
        _chunk(0.7, big_text, "c.md"),
    ]
    block = build_documentation_block(chunks, max_tokens=1100)

    assert "source=a.md" in block
    assert "source=b.md" in block
    assert "source=c.md" not in block
    assert estimate_tokens(block) <= 1100


def test_documentation_block_empty_for_no_chunks() -> None:
    assert build_documentation_block([], max_tokens=2000) == ""


class _StaticProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "static"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return GenerationResponse(
            provider="static", model="m", content="ok", tool_calls=[]
        )


def _chat_service(
    retriever: Any,
) -> tuple[ChatService, _StaticProvider]:
    provider = _StaticProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = ToolRegistry()
    executor = ToolExecutor(registry=registry, retailer=MagicMock())
    service = ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test"),
        tool_executor=executor,
        retriever=retriever,
    )
    return service, provider


def _handle(service: ChatService) -> None:
    asyncio.run(
        service.handle(
            ChatRequest(
                text="POS kaise use karein?", sessionId="s1", storeId=STORE_ID
            ),
            user={"sub": "u1"},
            request_id="r1",
            store_id=STORE_ID,
            access_token="token",
        )
    )


def test_chat_injects_retrieved_docs_into_system_prompt() -> None:
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[_chunk(0.9, "POS needs a paid plan.", "invoice/pos.md")]
    )
    service, provider = _chat_service(retriever)

    _handle(service)

    retriever.retrieve.assert_awaited_once_with("POS kaise use karein?")
    system = provider.requests[0].messages[0]
    assert system.role == "system"
    assert "POS needs a paid plan." in system.content


def test_chat_continues_without_docs_when_retrieval_fails() -> None:
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        side_effect=AppError(
            code="AI_PROVIDER_ERROR", message="embed down", status_code=502
        )
    )
    service, provider = _chat_service(retriever)

    _handle(service)

    system = provider.requests[0].messages[0]
    assert "Documentation" not in system.content


def test_chat_without_retriever_unchanged() -> None:
    service, provider = _chat_service(None)

    _handle(service)

    system = provider.requests[0].messages[0]
    assert "Documentation" not in system.content
