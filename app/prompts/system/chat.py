from app.rag.chunker import estimate_tokens
from app.rag.retriever import RetrievedChunk
from app.schemas.tool import ToolDefinition


def build_chat_system_prompt(
    *,
    language: str,
    store_id: str,
    tools: tuple[ToolDefinition, ...] | list[ToolDefinition],
    documentation: str = "",
) -> str:
    tool_names = ", ".join(tool.name for tool in tools) or "(none)"
    prompt = (
        "You are DragBizz store assistant.\n"
        f"Respond to the user in language tag: {language}.\n"
        f"Active storeId: {store_id}.\n"
        "Rules:\n"
        f"- You may only call these tools: {tool_names}.\n"
        "- Never invent IDs, amounts, stock, or customer data.\n"
        "- Live business data (sales, revenue, stock counts, prices, "
        "payments, balances) must come from tool calls only.\n"
        "- When a tool schema includes storeId, it must equal the active storeId.\n"
        "- Read tools may be executed by the server after you call them.\n"
    )
    if documentation:
        prompt += (
            "- Documentation below is only for how-to, features, plans, and "
            "errors. Never answer live numbers from Documentation — call the "
            "tool instead.\n"
            "- If a question needs both, call the tool for the numbers and "
            "use Documentation for the steps.\n"
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
