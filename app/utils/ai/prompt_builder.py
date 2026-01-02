from app.constants.ai import CONVERSATION_PROMPT_BASE, LANGUAGE_INSTRUCTION


def build_conversation_prompt(user_language: str = "english") -> str:
    return f"{CONVERSATION_PROMPT_BASE} {LANGUAGE_INSTRUCTION}"

