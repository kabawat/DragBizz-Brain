"""Version-controlled refusal copy for guard-blocked questions."""

from __future__ import annotations

import random

# Several short, human variants per language — pick one at random so
# repeated off-topic questions do not sound like the same canned reply.
_REFUSAL_MESSAGES: dict[str, tuple[str, ...]] = {
    "en": (
        "That one's outside what I cover — ask me about your store sales, "
        "stock, or DragBizz features?",
        "Hmm, not something I dig into. Billing, GST, stock, khata — those "
        "I can help with.",
        "Can't help with that topic. Got a DragBizz / shop question instead?",
        "Not really my lane. Sale, stock, payments, reports — fire away on "
        "those.",
        "I stick to the shop side of things. Anything about your DragBizz "
        "store?",
    ),
    "hi": (
        "Ye wala mere area ka nahi hai — sale, stock, ya DragBizz features "
        "poochho?",
        "Is topic pe main help nahi kar sakta. Store ka kuch poochna ho to "
        "bolo.",
        "General / coding cheezein nahi — shop ke sales, GST, stock pe "
        "poochho.",
        "Woh alag baat hai. DragBizz store se related kuch chahiye?",
        "Main sirf dukaan wali baaton pe hoon — billing, khata, reports. "
        "Kuch aisa poochho?",
    ),
    "gu": (
        "Aa topic mara area no nathi — sale, stock, ke DragBizz features "
        "puchho?",
        "Aa par hun madad nathi kari shakto. Store no kai prashna hoy to "
        "bolo.",
        "General / coding nathi — dukaan na sales, GST, stock par puchho.",
        "E alag vaat chhe. DragBizz store sathe related kai joiye?",
        "Hun fakt dukaan ni baato ma madad karu — billing, khata, reports. "
        "Kai aavu puchho?",
    ),
}

_DEFAULT_LANGUAGE = "hi"


def get_refusal_messages(language: str) -> tuple[str, ...]:
    prefix = language.split("-", 1)[0].lower()
    return _REFUSAL_MESSAGES.get(prefix, _REFUSAL_MESSAGES[_DEFAULT_LANGUAGE])


def get_refusal_message(language: str) -> str:
    return random.choice(get_refusal_messages(language))
