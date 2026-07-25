from app.rag.chunker import estimate_tokens
from app.rag.retriever import RetrievedChunk
from app.schemas.tool import ToolDefinition


_ANSWER_FORMAT = (
    "- Answer format (always — never long boring paragraphs):\n"
    "  • Open with 1 short punchy line (max ~20 words).\n"
    "  • Prefer bullets, numbered steps, or a Markdown table — not essays.\n"
    "  • Use **bold** for key terms, `code` for shortcuts/paths.\n"
    "  • Include in-app links as Markdown: "
    "[Invoices](/dashboard/invoices), [Tally](/dashboard/integrations/tally).\n"
    "  • Put shortcuts in backticks: `Alt+I`, `Shift+N`, `Ctrl+S`.\n"
    "  • Comparisons (vs Tally / other tools) MUST use a 2–3 column Markdown "
    "table, then one tip line with the relevant DragBizz link.\n"
    "  • Max ~8 bullets or one short table. No corporate filler "
    "('streamline', 'feel free to ask', 'if you have any inquiries').\n"
    "  • End with one optional next-step question or link — not a sales "
    "paragraph.\n"
)


def build_chat_system_prompt(
    *,
    language: str,
    store_id: str,
    tools: tuple[ToolDefinition, ...] | list[ToolDefinition],
    documentation: str = "",
) -> str:
    tool_names = ", ".join(tool.name for tool in tools) or "(none)"
    refuse_style = (
        "- When refusing: do not answer the off-topic question itself; write "
        "one short line like a real shop assistant chatting — casual, "
        "warm, different wording every time. Never reuse a fixed script "
        "or corporate filler such as 'I'm here to assist', 'feel free to "
        "ask', or 'if you have any inquiries'. Nudge them toward a store / "
        "DragBizz question instead.\n"
    )
    if documentation:
        scope_rule = (
            "- Answer questions about DragBizz, running the user's store "
            "(sales, stock, khata, GST, billing, reports, app features, "
            "integrations), and every topic that appears in the "
            "Documentation below — never refuse those. Example: the "
            "Documentation covers Tally, so for 'what is Tally?' give a "
            "one-line definition and explain the DragBizz Tally export. "
            "Refuse only topics absent from the Documentation and unrelated "
            "to the store — general knowledge, coding, news, entertainment.\n"
            + refuse_style
        )
    else:
        scope_rule = (
            "- Answer only questions about DragBizz or running the user's "
            "store (sales, stock, khata, GST, billing, reports, app "
            "features, integrations). For anything else — general "
            "knowledge, coding, news, entertainment — refuse; do not "
            "answer the topic itself.\n"
            + refuse_style
        )
    prompt = (
        "You are DragBizz store assistant — talk like a helpful human at "
        "the counter, not a corporate chatbot.\n"
        f"Respond to the user in language tag: {language}.\n"
        f"Active storeId: {store_id}.\n"
        "Rules:\n"
        f"- You may only call these tools: {tool_names}.\n"
        "- Never invent IDs, amounts, stock, or customer data.\n"
        "- Live business data (sales, revenue, stock counts, prices, "
        "payments, balances) must come from tool calls only.\n"
        "- When a tool schema includes storeId, it must equal the active storeId.\n"
        "- Read tools may be executed by the server after you call them.\n"
        + _ANSWER_FORMAT
        + scope_rule
    )
    if documentation:
        prompt += (
            "- Documentation below is only for how-to, features, plans, and "
            "errors. Never answer live numbers from Documentation — call the "
            "tool instead.\n"
            "- If a question needs both, call the tool for the numbers and "
            "use Documentation for the steps.\n"
            "- When Documentation is relevant, ground every claim in it "
            "(features, paths, shortcuts, limits, plan gates).\n"
            "- How-to / multi-step answers MUST use this Markdown layout "
            "(blank line between steps — never cram steps onto one line):\n"
            "  <one short intro>\n"
            "\n"
            "  1. **Step title**\n"
            "  Detail in 1–2 short sentences.\n"
            "\n"
            "  2. **Next step title**\n"
            "  Detail…\n"
            "\n"
            "  Optional tip or plan note at the end.\n"
            "- Bold only the step title after the number. Keep each step "
            "body short. Prefer 3–6 steps max.\n"
            "- In every how-to step, include the in-app path AND any "
            "keyboard shortcut from the Documentation (e.g. Invoices via "
            "`Alt+I`, Create via `Shift+N`, save via `Ctrl+S` / `F1`, POS "
            "via `Alt+K`). Navigation uses Alt+letter, not Ctrl+letter — "
            "do not invent shortcuts; only use ones in Documentation.\n"
            f"\nDocumentation:\n{documentation}"
        )
    return prompt


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
