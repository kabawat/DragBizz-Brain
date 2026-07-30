"""Choose RAG documentation token budget from question shape.

How-to questions keep the full docs budget; strong action/live cues use the
smaller action budget so invoice turns do not re-pay ~2k doc tokens on every
LLM call. Default is full budget when neither side matches clearly.
"""

from __future__ import annotations

import re

# Prefer how-to when both match (e.g. "POS se bill kaise banau?").
_HOW_TO_CUES = (
    "kaise",
    "kaisein",
    "karein",
    "karu",
    "how to",
    "how do i",
    "how do we",
    "steps",
    "guide",
)

_ACTION_CUES = (
    "bill banao",
    "bill bana",
    "invoice banao",
    "invoice bana",
    "create invoice",
    "create bill",
    "aaj ki sale",
    "kitni",
    "kitna",
    "kitne",
    "dikhao",
    "current price",
    "out of stock",
    "stock me",
    "payments",
)

_HOW_TO_RE = re.compile(
    "|".join(re.escape(cue) for cue in _HOW_TO_CUES),
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    "|".join(re.escape(cue) for cue in _ACTION_CUES),
    re.IGNORECASE,
)


def rag_docs_budget_for_question(
    question: str,
    *,
    full_budget: int,
    action_budget: int,
) -> int:
    text = question.strip()
    if not text:
        return full_budget
    if _HOW_TO_RE.search(text):
        return full_budget
    if _ACTION_RE.search(text):
        return min(action_budget, full_budget)
    return full_budget
