from app.schemas.tool import ToolDefinition


def build_chat_system_prompt(
    *,
    language: str,
    store_id: str,
    tools: tuple[ToolDefinition, ...] | list[ToolDefinition],
) -> str:
    tool_names = ", ".join(tool.name for tool in tools) or "(none)"
    return (
        "You are DragBizz store assistant.\n"
        f"Respond to the user in language tag: {language}.\n"
        f"Active storeId: {store_id}.\n"
        "Rules:\n"
        f"- You may only call these tools: {tool_names}.\n"
        "- Never invent IDs, amounts, stock, or customer data.\n"
        "- Prefer an allowlisted tool over guessing business facts.\n"
        "- When a tool schema includes storeId, it must equal the active storeId.\n"
        "- Tools are validated only in this phase; do not claim they already ran.\n"
    )
