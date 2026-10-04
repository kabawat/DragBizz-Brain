from app.rag.chunker import estimate_tokens
from app.rag.models import RetrievedChunk
from app.schemas.tool import ToolDefinition, ToolRisk

_INVOICE_CHAIN_TOOLS = frozenset(
    {
        "create_invoice_draft",
        "update_invoice_draft",
        "release_invoice",
    }
)

def _answer_format(*, with_docs: bool) -> str:
    link_rule = (
        "- In-app links only when relevant to THIS question and present in "
        "retrieved docs (e.g. [Invoices](/dashboard/invoices)). Never invent "
        "paths. do not mention Tally unless the user asked about Tally / "
        "accounting export.\n"
        if with_docs
        else (
            "- In-app links only when relevant to THIS question "
            "(e.g. [Invoices](/dashboard/invoices)). Never invent paths. "
            "do not mention Tally unless the user asked about Tally / "
            "accounting export.\n"
        )
    )
    return (
        "- Answer format: 1 short opener (~20 words), then bullets / numbered "
        "steps / a small Markdown table — not essays. Bold key terms; "
        "`code` for shortcuts. Max ~8 bullets. No corporate filler.\n"
        + link_rule
        + "- Comparisons (vs Tally / other tools) only when asked: 2–3 column "
        "Markdown table + one matching DragBizz link.\n"
    )

_NEITHER_FORMAT = (
    "- Keep replies to one short warm line. No essays, no tool talk, "
    "no invented store numbers.\n"
)

_HOWTO_LAYOUT = (
    "- How-to answers: short intro, then numbered steps with a blank line "
    "between each — `1. **Title**` then 1–2 short detail lines. Prefer "
    "3–6 steps. Include in-app path and any shortcut from Documentation "
    "only (Alt+letter navigation; never invent shortcuts).\n"
)


def build_chat_system_prompt(
    *,
    language: str,
    store_id: str,
    tools: tuple[ToolDefinition, ...] | list[ToolDefinition],
    documentation: str = "",
    routing: str = "unknown",
) -> str:
    """Assemble system rules for the turn's routing + offered tools.

    ``routing`` is ``tools`` / ``docs`` / ``both`` / ``neither`` / ``unknown``.
    Write / sensitive /
    invoice-chaining rules are included only when those tools are offered.
    """
    tool_names = {tool.name for tool in tools}
    has_tools = bool(tools)
    has_write = any(tool.risk == ToolRisk.WRITE for tool in tools)
    has_sensitive = any(tool.risk == ToolRisk.SENSITIVE for tool in tools)
    has_invoice_chain = bool(tool_names & _INVOICE_CHAIN_TOOLS)
    has_create_customer = "create_customer" in tool_names

    if documentation:
        scope_rule = (
            "- Answer DragBizz / store topics and anything covered in "
            "Documentation below. Refuse unrelated general knowledge, "
            "coding, news, entertainment.\n"
            "- When refusing: one short casual line (vary wording); nudge "
            "toward a store / DragBizz question. No corporate filler.\n"
        )
    else:
        scope_rule = (
            "- Answer only DragBizz or store topics (sales, stock, khata, "
            "GST, billing, reports, features, integrations). Refuse "
            "unrelated general knowledge, coding, news, entertainment.\n"
            "- When refusing: one short casual line (vary wording); nudge "
            "toward a store / DragBizz question. No corporate filler.\n"
        )

    parts: list[str] = [
        "You are DragBizz store assistant — helpful counter staff, not a "
        "corporate chatbot.\n",
        f"Respond to the user in language tag: {language}.\n",
        f"Active storeId: {store_id}.\n",
        "Rules:\n",
    ]

    if routing == "neither":
        parts.append(_NEITHER_FORMAT)
        parts.append(scope_rule)
        return "".join(parts)

    if has_tools:
        allowlist = ", ".join(tool.name for tool in tools)
        parts.append(f"- You may only call these tools: {allowlist}.\n")
        parts.append("- Never invent IDs, amounts, stock, or customer data.\n")
        parts.append(
            "- Live business data (sales, revenue, stock counts, prices, "
            "payments, balances) must come from tool calls only.\n"
        )
        parts.append(
            "- Tool storeId args must equal the active storeId. "
            "Read tools may run after you call them.\n"
        )
    else:
        parts.append(
            "- Never invent live store numbers (sales, stock, prices, "
            "balances). If you lack a tool result, say you do not have "
            "that live figure.\n"
        )

    if has_write:
        write_names = ", ".join(
            tool.name for tool in tools if tool.risk == ToolRisk.WRITE
        )
        parts.append(
            f"- Write tools ({write_names}) may auto-execute. "
            "Inputs must come from the user or prior real tool results. "
            "Never invent, guess, or 'pick for them' a customer name, "
            "phone, email, product, quantity, or amount — even if they say "
            "'as you wish', 'koi bhi', 'anything', or 'suggest' without the "
            "value. Then: do NOT call the write tool; ask for the exact "
            "name and 10-digit phone (or email).\n"
        )
        parts.append(
            "- After a successful write with openPath, end with a Markdown "
            "link using that openPath EXACTLY (relative in-app path only; "
            "no https:// or invented ids) — e.g. "
            "[Open customer](/dashboard/customers/<id>) or "
            "[Open invoice](/dashboard/invoices/<id>).\n"
        )
        parts.append(
            "- Never invent customer/product ObjectIds — search or reuse "
            "prior tool-result IDs. "
            "ledger_credit = customer PAYMENT; ledger_debit = DEBIT on khata.\n"
        )

    if has_sensitive:
        parts.append(
            "- Sensitive tools (release_invoice) NEVER auto-run — calling "
            "only stages confirmation. Do not claim release until the user "
            "confirms in the app.\n"
        )

    if has_invoice_chain or has_create_customer:
        parts.append(
            "- Finish the WHOLE request in one turn by chaining tools "
            "(e.g. search_customer + search_product → create_invoice_draft). "
            "Never pause to ask permission or say 'shall I proceed' for "
            "steps the user already asked for.\n"
        )
        parts.append(
            "- Named customer: FIRST search_customer. Only create_customer "
            "when search has no match AND user gave phone/email. If "
            "create_customer reports existing, use that id; else "
            "search_customer again. Never continue without a real customer id.\n"
        )

    if has_invoice_chain:
        parts.append(
            "- Named-customer bills: create_invoice_draft MUST include that "
            "customerId (no walk-in). Resolve via search_customer / "
            "create_customer, or link later with update_invoice_draft.\n"
        )
        parts.append(
            "- create_invoice_draft is DRAFT only. After success, say draft "
            "is ready and they must Confirm in the app to release. Call "
            "release_invoice only for an existing draft with a real "
            "invoiceId. At most ONE draft per request — if a draft already "
            "exists and user says haan/yes/confirm/release, call "
            "release_invoice (do not create another). To replace Walk-in "
            "after draft: search/create customer then update_invoice_draft.\n"
        )

    parts.append(_answer_format(with_docs=bool(documentation)))
    parts.append(scope_rule)

    if documentation:
        if has_tools:
            parts.append(
                "- Documentation is for how-to / features / plans / errors "
                "only. Never answer live numbers from Documentation — call "
                "the tool instead. If both are needed, call the tool for "
                "the numbers and use Documentation for the steps.\n"
            )
        else:
            parts.append(
                "- Documentation is for how-to / features / plans / errors "
                "only. Never answer live numbers from Documentation.\n"
            )
        parts.append(
            "- Ground every docs claim in Documentation "
            "(features, paths, shortcuts, limits, plan gates).\n"
        )
        parts.append(_HOWTO_LAYOUT)
        parts.append(f"\nDocumentation:\n{documentation}")

    return "".join(parts)


def build_documentation_block(
    chunks: list[RetrievedChunk], *, max_tokens: int
) -> str:
    """Format retrieved chunks with source citations under a token budget.

    Chunks arrive score-descending; lowest-score chunks are dropped first.
    """
    entries: list[str] = []
    used_tokens = 0
    for index, chunk in enumerate(chunks, start=1):
        source = chunk.metadata.get("source", "unknown")
        entry = f"[{index}] source={source}\n{chunk.text}"
        entry_tokens = estimate_tokens(entry)
        if used_tokens + entry_tokens > max_tokens:
            break
        entries.append(entry)
        used_tokens += entry_tokens
    return "\n\n".join(entries)
