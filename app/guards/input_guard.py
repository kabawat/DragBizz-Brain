from __future__ import annotations

import re
from dataclasses import dataclass

# Deliberately conservative: false negatives are acceptable (system prompt +
# tool allowlist still constrain the model); false positives block real users.
_PROMPT_INJECTION_PATTERNS = (
    r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|your)\s+"
    r"(?:instructions|rules|prompts?)",
    r"disregard\s+(?:all\s+|any\s+)?(?:previous|prior|above|your)\s+"
    r"(?:instructions|rules|prompts?)",
    r"forget\s+(?:everything|all\s+previous|your\s+(?:instructions|rules))",
    r"(?:reveal|show|print|repeat|output)\s+(?:me\s+)?your\s+"
    r"(?:system\s+)?(?:prompt|instructions)",
    r"you\s+are\s+(?:now|no\s+longer)\s+",
    r"pretend\s+(?:to\s+be|you\s+are)\s+",
    r"jailbreak",
    r"\bdan\s+mode\b",
    r"(?:^|\n)\s*(?:system|assistant)\s*:",
    r"\[\s*system\s*\]",
)

_OFF_TOPIC_PATTERNS = (
    r"write\s+(?:me\s+)?(?:a\s+)?(?:poem|essay|story|song|rap|joke)",
    r"(?:poem|essay|story|song|rap|joke)\s+(?:likho|likh\s+do|banao)",
    r"who\s+(?:won|will\s+win)\s+the\s+(?:match|election|world\s+cup)",
    r"capital\s+of\s+",
    r"solve\s+(?:this\s+)?(?:equation|math\s+problem)",
)

_INJECTION_RE = re.compile("|".join(_PROMPT_INJECTION_PATTERNS), re.IGNORECASE)
_OFF_TOPIC_RE = re.compile("|".join(_OFF_TOPIC_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    category: str | None = None
    matched: str | None = None


class InputGuard:
    def evaluate(self, text: str) -> GuardDecision:
        injection = _INJECTION_RE.search(text)
        if injection:
            return GuardDecision(
                allowed=False,
                category="PROMPT_INJECTION",
                matched=injection.group(0),
            )

        off_topic = _OFF_TOPIC_RE.search(text)
        if off_topic:
            return GuardDecision(
                allowed=False,
                category="OFF_TOPIC",
                matched=off_topic.group(0),
            )

        return GuardDecision(allowed=True)
