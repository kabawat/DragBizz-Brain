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

_DEFAULT_LANGUAGE = "hi"


def get_fallback_message(language: str) -> str:
    prefix = language.split("-", 1)[0].lower()
    return _FALLBACK_MESSAGES.get(prefix, _FALLBACK_MESSAGES[_DEFAULT_LANGUAGE])
