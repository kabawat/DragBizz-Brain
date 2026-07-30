"""Tool descriptions stay short (schemas still dominate token cost)."""

from app.tools.definitions import (
    READ_TOOL_DEFINITIONS,
    SENSITIVE_TOOL_DEFINITIONS,
    WRITE_TOOL_DEFINITIONS,
)


def test_tool_descriptions_stay_concise() -> None:
    definitions = (
        *READ_TOOL_DEFINITIONS,
        *WRITE_TOOL_DEFINITIONS,
        *SENSITIVE_TOOL_DEFINITIONS,
    )
    for definition in definitions:
        assert len(definition.description) <= 140, definition.name
    total = sum(len(definition.description) for definition in definitions)
    assert total <= 1100
