from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from app.schemas.tool import ToolDefinition, ToolResult
from app.tools.context import ToolContext

ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register_definition(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"Tool '{definition.name}' is already registered")
        self._definitions[definition.name] = definition

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.register_definition(definition)
        self._handlers[definition.name] = handler

    def get_definition(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise KeyError(f"Tool '{name}' is not registered") from exc

    def get_handler(self, name: str) -> ToolHandler:
        self.get_definition(name)
        try:
            return self._handlers[name]
        except KeyError as exc:
            raise KeyError(f"Tool '{name}' has no handler") from exc

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            self._definitions[name] for name in sorted(self._definitions)
        )

    def definitions_for(self, names: Iterable[str]) -> tuple[ToolDefinition, ...]:
        selected = set(names) & self._definitions.keys()
        return tuple(self._definitions[name] for name in sorted(selected))
