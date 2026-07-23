"""Phase 7 — RAG vs tool routing eval.

Runs every case in ``tests/eval/routing_cases.json`` through ChatService with
a scripted fake provider. The provider simulates the *expected* routing for
each case; the assertions verify the deterministic parts of the pipeline:

- the system prompt always carries the tools-vs-docs routing rules,
- all read tools stay offered to the model even when a docs block is present,
- expected tool calls still validate and execute with docs in the prompt
  (the "docs distract the model from tools" regression from the phase doc),
- docs-only and small-talk answers produce no tool results.

Whether the live LLM actually picks the expected route is a manual eval —
the JSON file doubles as the seed question set for that.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.rag.retriever import RetrievedChunk
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolResult
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"
ALL_TOOL_NAMES = {d.name for d in READ_TOOL_DEFINITIONS}

_CASES_PATH = Path(__file__).parent.parent / "eval" / "routing_cases.json"
_CASES: list[dict[str, Any]] = json.loads(_CASES_PATH.read_text())["cases"]


def _tool_arguments(name: str) -> dict[str, Any]:
    arguments: dict[str, Any] = {"storeId": STORE_ID}
    if name == "search_product":
        arguments["query"] = "Parle-G"
    return arguments


class _ScriptedProvider(ModelProvider):
    """Fake provider that answers with the routing expected for the case."""

    def __init__(self, tool_names: list[str]) -> None:
        self._tool_names = tool_names
        self.requests: list[GenerationRequest] = []

    @property
    def name(self) -> str:
        return "scripted"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        tool_calls = [
            ToolCall(id=f"c{i}", name=name, arguments=_tool_arguments(name))
            for i, name in enumerate(self._tool_names)
        ]
        return GenerationResponse(
            provider="scripted",
            model="m",
            content="" if tool_calls else "answer",
            tool_calls=tool_calls,
        )


class _FakeRetriever:
    """Returns one chunk when the case has a doc_source, else nothing."""

    def __init__(self, doc_source: str | None) -> None:
        self._doc_source = doc_source

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        if self._doc_source is None:
            return []
        return [
            RetrievedChunk(
                text=f"Steps from {self._doc_source}.",
                metadata={"source": self._doc_source},
                score=0.9,
            )
        ]


def _fake_handler(name: str):
    async def handler(arguments: dict[str, Any], context: Any) -> ToolResult:
        return ToolResult(tool=name, success=True, data={"ok": True})

    return handler


def _run_case(case: dict[str, Any]) -> tuple[Any, _ScriptedProvider]:
    provider = _ScriptedProvider(case["expected_tools"])
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)

    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register(definition, _fake_handler(definition.name))

    service = ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test"),
        tool_executor=ToolExecutor(registry=registry, retailer=MagicMock()),
        retriever=_FakeRetriever(case["doc_source"]),
    )
    response = asyncio.run(
        service.handle(
            ChatRequest(
                text=case["question"],
                sessionId="s1",
                storeId=STORE_ID,
                language=case["language"],
            ),
            user={"sub": "u1"},
            request_id="r1",
            store_id=STORE_ID,
            access_token="token",
        )
    )
    return response, provider


def test_eval_set_has_expected_size_and_mix() -> None:
    assert len(_CASES) == 20
    routings = {case["expected_routing"] for case in _CASES}
    assert routings == {"tools", "docs", "both", "neither"}
    for case in _CASES:
        if case["expected_routing"] in {"tools", "both"}:
            assert case["expected_tools"], case["id"]
            assert set(case["expected_tools"]) <= ALL_TOOL_NAMES, case["id"]
        else:
            assert case["expected_tools"] == [], case["id"]
        if case["expected_routing"] in {"docs", "both"}:
            assert case["doc_source"], case["id"]


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_routing_case(case: dict[str, Any]) -> None:
    response, provider = _run_case(case)

    request = provider.requests[0]
    system = request.messages[0].content

    # Routing rules are always in the system prompt.
    assert "must come from tool calls only" in system

    # All read tools stay offered to the model, docs block or not.
    assert {t.name for t in (request.tools or [])} == ALL_TOOL_NAMES

    if case["doc_source"]:
        assert f"source={case['doc_source']}" in system
        assert "Never answer live numbers from Documentation" in system
    else:
        assert "Documentation:" not in system

    executed = [r.tool for r in response.tool_results]
    if case["expected_routing"] in {"tools", "both"}:
        # Tool path must survive with docs present — no regression.
        assert executed == case["expected_tools"]
        assert all(r.success for r in response.tool_results)
    else:
        assert executed == []
        assert response.message == "answer"


def test_docs_block_does_not_drop_tool_call() -> None:
    """Direct regression check: docs present + tool call still executes."""
    case = next(c for c in _CASES if c["expected_routing"] == "both")
    response, provider = _run_case(case)

    system = provider.requests[0].messages[0].content
    assert "Documentation:" in system
    assert [r.tool for r in response.tool_results] == case["expected_tools"]
