"""AI-only write idempotency store package.

Kept as its own package (not folded into executors/tools) so lifespan can
inject InMemory now and Redis later beside sessions/confirmations/usage.
"""

from app.idempotency.store import (
    InMemoryIdempotencyStore,
    build_idempotency_key,
)

__all__ = ["InMemoryIdempotencyStore", "build_idempotency_key"]
