"""Phase 9 — per-request metrics logging and indexer run outcomes."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.core.logging import JsonFormatter
from app.executors.tool_executor import ToolExecutor
from app.orchestrator.ai_gateway import AiGateway
from app.orchestrator.chat_service import ChatService
from app.orchestrator.model_router import ModelRouter
from app.providers.base import ModelProvider
from app.rag import indexer
from app.rag.retriever import RetrievedChunk
from app.schemas.chat import ChatRequest, GenerationRequest, GenerationResponse
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"
# Live-sale → tools routing (RAG skipped). How-to → docs routing (RAG runs).
QUESTION_TOOLS = "aaj ki sale kitni hui?"
QUESTION_DOCS = "POS se bill kaise banau?"


# ------------------------------------------------------------ JsonFormatter


def test_json_formatter_includes_metrics_dict() -> None:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Chat request metrics", args=(), exc_info=None,
    )
    record.metrics = {"latency_ms": 12.5, "tools_called": ["today_sale"]}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["metrics"] == {
        "latency_ms": 12.5,
        "tools_called": ["today_sale"],
    }


def test_json_formatter_omits_metrics_when_absent() -> None:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="plain", args=(), exc_info=None,
    )
    assert "metrics" not in json.loads(JsonFormatter().format(record))


# ------------------------------------------------------ chat request metrics


class _StaticProvider(ModelProvider):
    @property
    def name(self) -> str:
        return "static"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(
            provider="static",
            model="gpt-4o-mini",
            content="POS kholen aur bill banayen.",
            tool_calls=[],
            input_tokens=100,
            output_tokens=50,
        )


def _run_chat(retriever, *, text: str = QUESTION_DOCS) -> None:
    provider = _StaticProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = ToolRegistry()
    service = ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test"),
        tool_executor=ToolExecutor(registry=registry, retailer=MagicMock()),
        retriever=retriever,
    )
    asyncio.run(
        service.handle(
            ChatRequest(text=text, sessionId="s1", storeId=STORE_ID),
            user={"sub": "u1"},
            request_id="r1",
            store_id=STORE_ID,
            access_token="token",
        )
    )


def _metrics_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    records = [
        r for r in caplog.records if r.getMessage() == "Chat request metrics"
    ]
    assert len(records) == 1
    return records[0]


def test_chat_logs_structured_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[
            RetrievedChunk(
                id="p1",
                text="POS steps.",
                metadata={"source": "invoice-pos.md"},
                score=0.91234,
            )
        ]
    )
    with caplog.at_level(logging.INFO):
        _run_chat(retriever)

    metrics = _metrics_record(caplog).metrics
    assert metrics["provider"] == "static"
    assert metrics["model"] == "gpt-4o-mini"
    assert metrics["input_tokens"] == 100
    assert metrics["output_tokens"] == 50
    # 100 * 0.15/1M + 50 * 0.60/1M
    assert metrics["est_cost_usd"] == pytest.approx(0.000045)
    assert metrics["latency_ms"] >= 0
    assert metrics["retrieved_docs"] == [
        {"id": "p1", "source": "invoice-pos.md", "score": 0.9123}
    ]
    assert metrics["tools_called"] == []
    assert metrics["rag_cache_hit"] is False
    assert metrics["prompt_system_tokens"] > 0
    assert metrics["prompt_user_tokens"] > 0
    assert "prompt_tools_tokens" in metrics
    assert "prompt_rag_tokens" in metrics
    assert "prompt_history_tokens" in metrics


def test_metrics_never_contain_question_or_answer_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    with caplog.at_level(logging.INFO):
        _run_chat(retriever, text=QUESTION_TOOLS)

    blob = json.dumps(_metrics_record(caplog).metrics)
    assert QUESTION_TOOLS not in blob
    assert "POS kholen" not in blob
    assert "u1" not in blob


def test_metrics_cost_none_when_provider_omits_usage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _NoUsageProvider(_StaticProvider):
        async def generate(
            self, request: GenerationRequest
        ) -> GenerationResponse:
            return GenerationResponse(
                provider="static", model="m", content="ok", tool_calls=[]
            )

    provider = _NoUsageProvider()
    router = ModelRouter()
    router.register(provider)
    router.set_active(provider.name)
    registry = ToolRegistry()
    service = ChatService(
        gateway=AiGateway(router),
        tool_registry=registry,
        settings=Settings(environment="test"),
        tool_executor=ToolExecutor(registry=registry, retailer=MagicMock()),
    )
    with caplog.at_level(logging.INFO):
        asyncio.run(
            service.handle(
                ChatRequest(
                    text=QUESTION_TOOLS, sessionId="s1", storeId=STORE_ID
                ),
                user={"sub": "u1"},
                request_id="r1",
                store_id=STORE_ID,
                access_token="token",
            )
        )

    metrics = _metrics_record(caplog).metrics
    assert metrics["est_cost_usd"] is None
    assert metrics["input_tokens"] is None


# ------------------------------------------------------- indexer run outcome


def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        indexer, "get_settings", lambda: Settings(environment="test")
    )


def test_indexer_main_success_logs_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_settings(monkeypatch)

    async def fake_run(settings, root):
        return MagicMock()

    monkeypatch.setattr(indexer, "_run_cli", fake_run)
    with caplog.at_level(logging.INFO):
        exit_code = indexer.main(["--root", str(tmp_path)])

    assert exit_code == 0
    assert any(
        "Index run completed" in r.getMessage() for r in caplog.records
    )


def test_indexer_main_failure_logs_marker_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_settings(monkeypatch)

    async def fake_run(settings, root):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(indexer, "_run_cli", fake_run)
    with caplog.at_level(logging.ERROR):
        exit_code = indexer.main(["--root", str(tmp_path)])

    assert exit_code == 1
    failures = [
        r for r in caplog.records if "Index run FAILED" in r.getMessage()
    ]
    assert len(failures) == 1
    assert failures[0].exc_info is not None
