"""Detect abusive user turns so the chat persona can escalate gently."""

from __future__ import annotations

import re
from collections.abc import Sequence

# Romanized Hindi + English insults. Keep this narrow — false positives on
# normal shop talk (e.g. "sale") are worse than missing a mild swear.
_ABUSE_PATTERNS = (
    r"\bmadarchod\b",
    r"\bmaderchod\b",
    r"\bbehenchod\b",
    r"\bbhenchod\b",
    r"\bbhnchod\b",
    r"\bbhonsdi\b",
    r"\bbhosdi\b",
    r"\bbhosdike\b",
    r"\bchutiya\b",
    r"\bchutiye\b",
    r"\bchutiyo\b",
    r"\bharami\b",
    r"\bharamzada\b",
    r"\bgandu\b",
    r"\bganduu\b",
    r"\blund\b",
    r"\bloda\b",
    r"\blode\b",
    r"\brandi\b",
    r"\brandi\w*\b",
    r"\bsaala\b",
    r"\bsaale\b",
    r"\bsalee\b",
    r"\bkutte\b",
    r"\bkutta\b",
    r"\bkamine\b",
    r"\bkamina\b",
    r"\bmc\b",
    r"\bbc\b",
    r"\bf+u+c?k(?:ing|er|ed)?\b",
    r"\bshit\b",
    r"\bbitch\b",
    r"\basshole\b",
    r"\bdickhead\b",
    r"\bmotherfucker\b",
)

_ABUSE_RE = re.compile("|".join(_ABUSE_PATTERNS), re.IGNORECASE)

# Same meaning, different wording — rotate so it never feels copy-paste.
_FIRM_LINES = (
    "Dhandhe pe dhyan dega to hi dhanda increase hoga, bakchodi karne se nahi.",
    "Seth ji, dukaan pe focus karoge tabhi growth aayegi — ye bakchodi se "
    "bill nahi badhega.",
    "Bhai ji, time business pe lagao; gaali-galoch se counter nahi chalega.",
    "Sahab ji, dhanda tab badhega jab kaam pe dhyan doge — bakchodi free "
    "me bhi loss hai.",
    "Mitr, seedhi baat: mehnat pe focus, warna sirf shor rahega faayda nahi.",
    "Dost, counter sambhalo pehle — bakchodi se na sale aati hai na customer.",
    "Arre bhai, gaali se inventory nahi bharegi. Kaam karo, dhanda khud badhega.",
    "Sun seth: respect se baat karo aur business pe lag jao — bakchodi bandh karo.",
)


def contains_abuse(text: str) -> bool:
    return bool(text and _ABUSE_RE.search(text))


def count_abuse_strikes(
    prior_user_texts: Sequence[str] | None,
    current_text: str,
) -> int:
    """How many user turns in this session (including current) used abuse."""
    strikes = 0
    for text in prior_user_texts or ():
        if isinstance(text, str) and contains_abuse(text):
            strikes += 1
    if contains_abuse(current_text):
        strikes += 1
    return strikes


def _firm_line_for_strike(strikes: int) -> str:
    # Rotate so 3rd, 4th, 5th… each get a different stock line.
    index = max(0, strikes - 3) % len(_FIRM_LINES)
    return _FIRM_LINES[index]


def abuse_tone_rule(strikes: int) -> str:
    if strikes <= 0:
        return ""
    if strikes >= 3:
        suggested = _firm_line_for_strike(strikes)
        others = [line for line in _FIRM_LINES if line != suggested]
        sample = "; ".join(f'"{line}"' for line in others[:4])
        return (
            "User has abused multiple times this session (3rd+). Reply "
            "firmly but still respectful — no matching gaali, no soft "
            "laugh-off. Use ONE fresh Hinglish line with the SAME meaning "
            f"(business pe dhyan, bakchodi se growth nahi). Suggested this "
            f'turn: "{suggested}". Other vibes you may paraphrase instead: '
            f"{sample}. Never paste the exact same sentence you already "
            "used earlier in this chat. Optionally one short offer to help "
            "with a real store question + at most one emoji (🙏 or 💼).\n"
        )
    return (
        "User used gaali/abuse. Reply warm and respectful like a dost — "
        "lightly tease with bhai ji / seth ji vibe, 1 emoji ok (😅 or 🙏), "
        "no matching gaali, no lectures. If they also asked something "
        "about the store, still answer that. Keep it to 1–2 short lines. "
        "Vary wording each time; do not reuse the same soft line.\n"
    )
