"""Version-controlled refusal copy for guard-blocked questions."""

_REFUSAL_MESSAGES = {
    "en": (
        "I can only help with your DragBizz store — sales, stock, products, "
        "customers, khata, and how-to questions. Please ask a store question."
    ),
    "hi": (
        "Main sirf aapke DragBizz store mein madad kar sakta hoon — sale, "
        "stock, products, customers, khata aur app se jude sawaal. Kripya "
        "store se juda sawaal poochhein."
    ),
    "gu": (
        "Hun matra tamara DragBizz store mate madad kari shakun chhun — "
        "sale, stock, products, customers, khata ane app na prashno. "
        "Krupa kari store no prashna puchho."
    ),
}

_DEFAULT_LANGUAGE = "hi"


def get_refusal_message(language: str) -> str:
    prefix = language.split("-", 1)[0].lower()
    return _REFUSAL_MESSAGES.get(prefix, _REFUSAL_MESSAGES[_DEFAULT_LANGUAGE])
