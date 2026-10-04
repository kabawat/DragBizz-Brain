"""Session history, RAG retrieval, and chat message assembly."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.config import Settings
from app.core.exceptions import AppError
from app.observability.events import RAG_RETRIEVE, emit_event
from app.observability.metrics import MetricsRegistry
from app.orchestrator.prompt_tokens import (
    PromptTokenBreakdown,
    estimate_prompt_token_breakdown,
)
from app.orchestrator.rag_budget import rag_docs_budget_for_routing
from app.orchestrator.tool_selector import RoutingLabel, should_retrieve_docs
from app.prompts.system.chat import (
    build_chat_system_prompt,
    build_documentation_block,
)
from app.rag.models import RetrievedChunk
from app.rag.retrieval_cache import NoOpRagCache, RagCache
from app.rag.retriever import Retriever
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolDefinition
from app.sessions import SessionStore, SessionTurn, turns_to_messages


@dataclass(frozen=True)
class ChatContext:
    prior_turns: list[SessionTurn]
    retrieved: list[RetrievedChunk]
    messages: list[ChatMessage]
    token_breakdown: PromptTokenBreakdown
    rag_cache_hit: bool = False
    docs_unavailable: bool = False


async def retrieve_documentation(
    retriever: Retriever | None,
    question: str,
    *,
    metrics: MetricsRegistry | None = None,
    cache_hit: bool = False,
) -> tuple[list[RetrievedChunk], bool]:
    """Returns (chunks, failed). failed=True when RAG/Qdrant errored."""
    if retriever is None:
        if metrics is not None:
            metrics.record_rag(0.0, failed=True, cache_hit=cache_hit)
        emit_event(
            RAG_RETRIEVE,
            level=logging.WARNING,
            failed=True,
            cache_hit=cache_hit,
        )
        return [], True
    started = time.perf_counter()
    try:
        chunks = await retriever.retrieve(question)
        latency_ms = (time.perf_counter() - started) * 1000
        if metrics is not None:
            metrics.record_rag(latency_ms, failed=False, cache_hit=cache_hit)
        emit_event(
            RAG_RETRIEVE,
            level=logging.DEBUG,
            failed=False,
            cache_hit=cache_hit,
            latency_ms=round(latency_ms, 1),
            chunks=len(chunks),
        )
        return chunks, False
    except AppError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        if metrics is not None:
            metrics.record_rag(latency_ms, failed=True, cache_hit=cache_hit)
        emit_event(
            RAG_RETRIEVE,
            level=logging.WARNING,
            failed=True,
            cache_hit=cache_hit,
            latency_ms=round(latency_ms, 1),
            error=exc.code,
            reason=exc.message,
        )
        return [], True


async def build_chat_context(
    *,
    sessions: SessionStore,
    retriever: Retriever | None,
    settings: Settings,
    question: str,
    language: str,
    session_id: str,
    user_id: str,
    store_id: str,
    tools: list[ToolDefinition],
    routing: RoutingLabel = "unknown",
    rag_cache: RagCache | None = None,
    metrics: MetricsRegistry | None = None,
) -> ChatContext:
    cache: RagCache = rag_cache or NoOpRagCache()
    prior_turns = await sessions.load_history(
        session_id=session_id,
        user_id=user_id,
        store_id=store_id,
    )
    docs_budget = rag_docs_budget_for_routing(
        routing,
        faq_budget=settings.rag.context_max_tokens,
        action_budget=settings.rag.context_max_tokens_action,
    )

    retrieved: list[RetrievedChunk] = []
    documentation = ""
    rag_cache_hit = False
    docs_unavailable = False
    if should_retrieve_docs(routing):
        cached_docs = await cache.get_documentation_block(
            question, budget=docs_budget
        )
        if cached_docs is not None:
            documentation = cached_docs
            rag_cache_hit = True
            # Still fetch chunk metadata for metrics when possible (may hit
            # the chunk cache without a second embed/search).
            retrieved, _ = await retrieve_documentation(
                retriever, question, metrics=metrics, cache_hit=True
            )
        else:
            retrieved, rag_failed = await retrieve_documentation(
                retriever, question, metrics=metrics, cache_hit=False
            )
            if rag_failed:
                # docs routing cannot invent how-to; both/unknown continue.
                if routing == "docs":
                    docs_unavailable = True
                documentation = ""
            else:
                documentation = build_documentation_block(
                    retrieved,
                    max_tokens=docs_budget,
                )
                await cache.set_documentation_block(
                    question, budget=docs_budget, block=documentation
                )

    if docs_unavailable:
        return ChatContext(
            prior_turns=prior_turns,
            retrieved=[],
            messages=[],
            token_breakdown=estimate_prompt_token_breakdown(
                system_content="",
                documentation="",
                tools=tools,
                history_messages=[],
                user_text=question,
            ),
            rag_cache_hit=False,
            docs_unavailable=True,
        )

    history_messages = turns_to_messages(prior_turns)
    system_content = build_chat_system_prompt(
        language=language,
        store_id=store_id,
        tools=tools,
        documentation=documentation,
        routing=routing,
    )
    messages = [
        ChatMessage(role="system", content=system_content),
        *history_messages,
        ChatMessage(role="user", content=question),
    ]
    token_breakdown = estimate_prompt_token_breakdown(
        system_content=system_content,
        documentation=documentation,
        tools=tools,
        history_messages=history_messages,
        user_text=question,
    )
    return ChatContext(
        prior_turns=prior_turns,
        retrieved=retrieved,
        messages=messages,
        token_breakdown=token_breakdown,
        rag_cache_hit=rag_cache_hit,
        docs_unavailable=False,
    )
