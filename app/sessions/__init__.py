"""Chat session memory package (Protocol + InMemory; Redis/Postgres later).

Intentional thin package: multiple orchestrator consumers share SessionStore
without owning a backend. Do not flatten into chat_service.
"""

from app.sessions.store import (
    InMemorySessionStore,
    SessionStore,
    SessionTurn,
    turns_to_messages,
)

__all__ = [
    "InMemorySessionStore",
    "SessionStore",
    "SessionTurn",
    "turns_to_messages",
]
