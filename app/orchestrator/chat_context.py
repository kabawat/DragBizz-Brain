"""Session history, RAG retrieval, and chat message assembly."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import Settings
from app.core.exceptions import AppError
from app.orchestrator.rag_budget import rag_docs_budget_for_question
from app.prompts.system.chat import (
    build_chat_system_prompt,
    build_documentation_block,
)
from app.rag.retriever import RetrievedChunk, Retriever
from app.schemas.chat import ChatMessage
from app.schemas.tool import ToolDefinition
from app.sessions import SessionStore, SessionTurn, turns_to_messages

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatContext:
    prior_turns: list[SessionTurn]
    retrieved: list[RetrievedChunk]
    messages: list[ChatMessage]


async def retrieve_documentation(
    retriever: Retriever | None,
    question: str,
) -> list[RetrievedChunk]:
    if retriever is None:
        return []
    try:
        return await retriever.retrieve(question)
    except AppError:
        logger.warning(
            "RAG retrieval failed; answering without documentation",
            exc_info=True,
        )
        return []


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
) -> ChatContext:
    prior_turns = await sessions.load_history(
        session_id=session_id,
        user_id=user_id,
        store_id=store_id,
    )
    retrieved = await retrieve_documentation(retriever, question)
    docs_budget = rag_docs_budget_for_question(
        question,
        full_budget=settings.rag_context_max_tokens,
        action_budget=settings.rag_context_max_tokens_action,
    )
    messages = [
        ChatMessage(
            role="system",
            content=build_chat_system_prompt(
                language=language,
                store_id=store_id,
                tools=tools,
                documentation=build_documentation_block(
                    retrieved,
                    max_tokens=docs_budget,
                ),
            ),
        ),
        *turns_to_messages(prior_turns),
        ChatMessage(role="user", content=question),
    ]
    return ChatContext(
        prior_turns=prior_turns,
        retrieved=retrieved,
        messages=messages,
    )
