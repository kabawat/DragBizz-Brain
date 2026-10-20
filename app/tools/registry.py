from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.schemas.tool import ToolAccessType, ToolDefinition, ToolDomain, ToolResult
from app.tools.context import ToolContext

ToolHandler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolEntry:
    name: str
    definition: ToolDefinition
    handler: ToolHandler
    domain: ToolDomain
    access_type: ToolAccessType
    requires_confirmation: bool
    required_permissions: tuple[str, ...] = ()


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._entries: dict[str, ToolEntry] = {}

    def register_definition(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"Tool '{definition.name}' is already registered")
        self._definitions[definition.name] = definition

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        *,
        domain: ToolDomain | None = None,
        required_permissions: tuple[str, ...] | None = None,
    ) -> None:
        self.register_definition(definition)
        self._handlers[definition.name] = handler
        resolved_domain = domain or definition.domain
        resolved_permissions = (
            required_permissions
            if required_permissions is not None
            else definition.required_permissions
        )
        self._entries[definition.name] = ToolEntry(
            name=definition.name,
            definition=definition,
            handler=handler,
            domain=resolved_domain,
            access_type=definition.access_type,
            requires_confirmation=definition.requires_confirmation,
            required_permissions=resolved_permissions,
        )

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

    def get_entry(self, name: str) -> ToolEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(f"Tool entry '{name}' is not registered") from exc

    def entries(self) -> tuple[ToolEntry, ...]:
        return tuple(self._entries[name] for name in sorted(self._entries))

    def entries_for_domain(
        self, domain: ToolDomain | str
    ) -> tuple[ToolEntry, ...]:
        target = domain.value if isinstance(domain, ToolDomain) else str(domain)
        return tuple(
            entry
            for entry in self.entries()
            if entry.domain.value == target
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            self._definitions[name] for name in sorted(self._definitions)
        )

    def definitions_for(self, names: Iterable[str]) -> tuple[ToolDefinition, ...]:
        selected = set(names) & self._definitions.keys()
        return tuple(self._definitions[name] for name in sorted(selected))

    def definitions_for_domain(
        self, domain: ToolDomain | str
    ) -> tuple[ToolDefinition, ...]:
        return tuple(e.definition for e in self.entries_for_domain(domain))

    def tools_by_domain(self) -> dict[ToolDomain, tuple[str, ...]]:
        result: dict[ToolDomain, list[str]] = {}
        for entry in self.entries():
            result.setdefault(entry.domain, []).append(entry.name)
        return {domain: tuple(names) for domain, names in result.items()}


def build_unified_tool_registry() -> ToolRegistry:
    """Canonical registry builder registering all definitions and handlers."""
    from app.tools.definitions import (
        READ_TOOL_DEFINITIONS,
        SENSITIVE_TOOL_DEFINITIONS,
        WRITE_TOOL_DEFINITIONS,
    )
    from app.tools.handlers.confirm_tools import SENSITIVE_TOOL_HANDLERS
    from app.tools.handlers.read_tools import READ_TOOL_HANDLERS
    from app.tools.handlers.write_tools import WRITE_TOOL_HANDLERS

    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        handler = READ_TOOL_HANDLERS[definition.name]
        registry.register(definition, handler)
    for definition in WRITE_TOOL_DEFINITIONS:
        handler = WRITE_TOOL_HANDLERS[definition.name]
        registry.register(definition, handler)
    for definition in SENSITIVE_TOOL_DEFINITIONS:
        handler = SENSITIVE_TOOL_HANDLERS[definition.name]
        registry.register(definition, handler)
    return registry
