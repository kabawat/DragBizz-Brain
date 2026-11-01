from __future__ import annotations

import math
import re
from collections.abc import Collection
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError

from app.core.exceptions import AppError
from app.schemas.tool import ToolCall, ToolDefinition
from app.tools.registry import ToolRegistry

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_ARGUMENT_DEPTH = 12
_MAX_ARGUMENT_STRING_LENGTH = 5_000
_MAX_ARGUMENT_CONTAINER_ITEMS = 100
_MAX_ARGUMENT_INTEGER = 10**15


class ToolCallValidator:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def validate(
        self,
        tool_calls: list[ToolCall],
        *,
        store_id: str,
        allowed_names: Collection[str] | None = None,
        agency_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[ToolCall]:
        if not tool_calls:
            return []

        validated: list[ToolCall] = []
        for call in tool_calls:
            definition = self._require_definition(
                call.name, allowed_names=allowed_names
            )
            arguments = dict(call.arguments)
            limit = arguments.get("limit")
            if isinstance(limit, int) and not isinstance(limit, bool) and limit > 50:
                arguments["limit"] = 50
            self._validate_argument_values(arguments)
            self._validate_schema(definition, arguments)
            self._validate_store_id(
                arguments,
                store_id,
                agency_id=agency_id,
                tenant_id=tenant_id,
            )
            validated.append(ToolCall(id=call.id, name=call.name, arguments=arguments))
        return validated

    def describe_errors(
        self,
        tool_calls: list[ToolCall],
        *,
        store_id: str,
        allowed_names: Collection[str] | None = None,
        agency_id: str | None = None,
        tenant_id: str | None = None,
    ) -> list[str]:
        errors: list[str] = []
        for call in tool_calls:
            try:
                self.validate(
                    [call],
                    store_id=store_id,
                    allowed_names=allowed_names,
                    agency_id=agency_id,
                    tenant_id=tenant_id,
                )
            except AppError as exc:
                errors.append(f"{call.name}: {exc.message}")
        return errors

    def _require_definition(
        self,
        name: str,
        *,
        allowed_names: Collection[str] | None,
    ) -> ToolDefinition:
        if allowed_names is not None and name not in allowed_names:
            raise AppError(
                code="TOOL_NOT_ALLOWED",
                message=f"Tool '{name}' is not allowlisted",
                status_code=400,
            )
        try:
            return self._registry.get_definition(name)
        except KeyError as exc:
            raise AppError(
                code="TOOL_NOT_ALLOWED",
                message=f"Tool '{name}' is not allowlisted",
                status_code=400,
            ) from exc

    def _validate_schema(
        self, definition: ToolDefinition, arguments: dict[str, Any]
    ) -> None:
        try:
            validator = Draft202012Validator(
                definition.parameters,
                format_checker=FormatChecker(),
            )
            validator.validate(arguments)
        except SchemaError as exc:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message=f"Invalid schema for tool '{definition.name}'",
                status_code=400,
            ) from exc
        except ValidationError as exc:
            path = ".".join(str(part) for part in exc.path) or "(root)"
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message=(
                    f"Invalid arguments for tool '{definition.name}' "
                    f"at {path}: {exc.message}"
                ),
                status_code=400,
            ) from exc

    def _validate_argument_values(self, value: Any, *, depth: int = 0) -> None:
        """Bound and type-check decoded arguments before any tool can execute."""
        if depth > _MAX_ARGUMENT_DEPTH:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool arguments exceed the maximum nesting depth",
                status_code=400,
            )
        if isinstance(value, str):
            if len(value) > _MAX_ARGUMENT_STRING_LENGTH:
                raise AppError(
                    code="TOOL_ARGS_INVALID",
                    message="Tool argument text exceeds the maximum length",
                    status_code=400,
                )
            if _CONTROL_CHAR_RE.search(value):
                raise AppError(
                    code="TOOL_ARGS_INVALID",
                    message="Tool argument text contains invalid control characters",
                    status_code=400,
                )
            return
        if isinstance(value, float) and not math.isfinite(value):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool numeric arguments must be finite",
                status_code=400,
            )
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and abs(value) > _MAX_ARGUMENT_INTEGER
        ):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool integer argument exceeds the supported range",
                status_code=400,
            )
        if isinstance(value, dict):
            if len(value) > _MAX_ARGUMENT_CONTAINER_ITEMS or not all(
                isinstance(key, str) for key in value
            ):
                raise AppError(
                    code="TOOL_ARGS_INVALID",
                    message="Tool argument object has invalid keys or is too large",
                    status_code=400,
                )
            for item in value.values():
                self._validate_argument_values(item, depth=depth + 1)
            return
        if isinstance(value, list):
            if len(value) > _MAX_ARGUMENT_CONTAINER_ITEMS:
                raise AppError(
                    code="TOOL_ARGS_INVALID",
                    message="Tool argument list is too large",
                    status_code=400,
                )
            for item in value:
                self._validate_argument_values(item, depth=depth + 1)
    def _validate_store_id(
        self,
        arguments: dict[str, Any],
        store_id: str,
        *,
        agency_id: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        if "agencyId" in arguments and (
            not agency_id or arguments["agencyId"] != agency_id
        ):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool agencyId does not match authenticated agency",
                status_code=400,
            )
        if "tenantId" in arguments and (
            not tenant_id or arguments["tenantId"] != tenant_id
        ):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool tenantId does not match authenticated tenant",
                status_code=400,
            )
        if "tenant" in arguments and (
            not tenant_id or arguments["tenant"] != tenant_id
        ):
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool tenant does not match authenticated tenant",
                status_code=400,
            )
        if "storeId" in arguments:
            if arguments["storeId"] != store_id:
                raise AppError(
                    code="TOOL_ARGS_INVALID",
                    message="Tool storeId must match the chat request storeId",
                    status_code=400,
                )
            arguments["storeId"] = store_id
