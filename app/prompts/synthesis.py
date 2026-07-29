"""Instructions for the post-tool grounded answer turn."""


def build_continuation_instruction(*, language: str) -> str:
    return (
        "Tool results are above. If finishing the user's request still "
        "needs more tool calls (e.g. you now have customer/product ids and "
        "must create the invoice draft), call those tools NOW — do not ask "
        "permission for steps the user already requested. Only when the "
        "request is complete, or blocked on info only the user can give, "
        "answer instead. For answers: use ONLY tool results for live "
        "business numbers; never invent IDs, amounts, stock, or customer "
        "data; if a tool failed, say so briefly without guessing numbers; "
        "if a successful write tool result includes openPath, include it "
        "as a Markdown link using that path exactly. "
        f"Respond in language tag: {language}."
    )


def build_synthesis_instruction(*, language: str) -> str:
    return (
        "Tool results are above. Answer the user's original question using "
        "ONLY those results for live business numbers (sales, stock, prices, "
        "payments, balances). You may use Documentation from the system "
        "prompt for how-to or feature context. "
        "Never invent IDs, amounts, stock, or customer data. "
        "If a tool failed, say so briefly without guessing numbers. "
        "If a successful write tool result includes openPath, include it as "
        "a Markdown link (e.g. [Open customer](/dashboard/customers/…)) — "
        "use that path exactly. "
        f"Respond in language tag: {language}."
    )
