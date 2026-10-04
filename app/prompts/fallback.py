"""Version-controlled safe fallback copy for output-guard failures."""

_FALLBACK_MESSAGES = {
    "en": (
        "I couldn't verify that answer against your store data. Please try "
        "asking again, or check the exact numbers in your DragBizz reports."
    ),
    "hi": (
        "Main is jawab ko aapke store data se verify nahi kar paya. Kripya "
        "dobara poochhein, ya exact numbers DragBizz reports mein dekhein."
    ),
    "gu": (
        "Hun aa jawab tamara store data sathe verify kari shakyo nathi. "
        "Krupa kari farithi puchho, athva exact numbers DragBizz reports "
        "ma juo."
    ),
}

_DOCS_UNAVAILABLE_MESSAGES = {
    "en": (
        "Help documentation is temporarily unavailable. "
        "Please try again in a moment — I won't invent how-to steps."
    ),
    "hi": (
        "Help documentation abhi unavailable hai. "
        "Thodi der baad try karein — main how-to steps invent nahi karunga."
    ),
    "gu": (
        "Help documentation halma unavailable che. "
        "Thodi vaar pachhi try karo — hun how-to steps invent nahi karish."
    ),
}

_BUDGET_MESSAGES = {
    "en": (
        "This request used too many steps. Please ask a shorter question "
        "or try again."
    ),
    "hi": (
        "Is request mein bahut zyada steps lag gaye. "
        "Chhota sawal poochhein ya dobara try karein."
    ),
    "gu": (
        "Aa request ma ghana steps thai gaya. "
        "Nanun prashna puchho athva farithi try karo."
    ),
}

_DEFAULT_LANGUAGE = "hi"


def get_fallback_message(language: str) -> str:
    prefix = language.split("-", 1)[0].lower()
    return _FALLBACK_MESSAGES.get(prefix, _FALLBACK_MESSAGES[_DEFAULT_LANGUAGE])


def get_docs_unavailable_message(language: str) -> str:
    prefix = language.split("-", 1)[0].lower()
    return _DOCS_UNAVAILABLE_MESSAGES.get(
        prefix, _DOCS_UNAVAILABLE_MESSAGES[_DEFAULT_LANGUAGE]
    )


def get_budget_exceeded_message(language: str) -> str:
    prefix = language.split("-", 1)[0].lower()
    return _BUDGET_MESSAGES.get(prefix, _BUDGET_MESSAGES[_DEFAULT_LANGUAGE])
