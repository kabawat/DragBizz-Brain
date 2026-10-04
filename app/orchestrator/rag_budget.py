"""Choose RAG documentation token budget from turn routing.

FAQ / how-to / both → ``faq_budget`` (~800–1000). Pure live-tool turns →
``action_budget`` (smaller; usually unused because retrieval is skipped).
Routing comes from ``resolve_turn_intent`` (single cue source of truth).
"""

from __future__ import annotations

# Unknown turns still retrieve docs, but sit beside five read schemas.
# Cap them below a large FAQ budget so retrieval does not dominate the prompt.
_UNKNOWN_DOCS_CAP = 1000


def rag_docs_budget_for_routing(
    routing: str,
    *,
    faq_budget: int,
    action_budget: int,
) -> int:
    if routing == "tools":
        return min(action_budget, faq_budget)
    if routing == "unknown":
        return min(faq_budget, _UNKNOWN_DOCS_CAP)
    return faq_budget
