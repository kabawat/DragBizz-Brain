from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.observability.context import get_request_id


class ToolResultStatus(StrEnum):
    SUCCESS_WITH_DATA = "success_with_data"
    SUCCESS_EMPTY = "success_empty"
    SUCCESS_PARTIAL = "success_partial"
    UNSUPPORTED = "unsupported"
    INVALID_INPUT = "invalid_input"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    DEPENDENCY_ERROR = "dependency_error"
    INTERNAL_ERROR = "internal_error"


class ToolPagination(BaseModel):
    cursor: str | None = None
    next_cursor: str | None = Field(
        default=None, alias="nextCursor", serialization_alias="nextCursor"
    )
    has_more: bool | None = Field(
        default=None, alias="hasMore", serialization_alias="hasMore"
    )
    page: int | None = Field(default=None, ge=1)
    page_size: int | None = Field(
        default=None, alias="pageSize", serialization_alias="pageSize", ge=1
    )
    total_count: int | None = Field(
        default=None, alias="totalCount", serialization_alias="totalCount", ge=0
    )

    model_config = {"populate_by_name": True}


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    SENSITIVE = "sensitive"


class ToolDomain(StrEnum):
    INVENTORY = "inventory"
    PROCUREMENT = "procurement"
    SALES = "sales"
    KHATA = "khata"
    FINANCE = "finance"
    GENERAL = "general"


class ToolAccessType(StrEnum):
    READ = "read"
    WRITE = "write"


class ToolSideEffect(StrEnum):
    NONE = "none"
    DRAFT = "draft"
    MUTATION = "mutation"


class ToolRetryPolicy(StrEnum):
    SAFE_READ = "safe_read"
    IDEMPOTENCY_KEY = "idempotency_key"
    NEVER = "never"


class ToolEffectStatus(StrEnum):
    NOT_APPLIED = "not_applied"
    APPLIED = "applied"
    UNKNOWN = "unknown"


class ToolDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=500)
    risk: ToolRisk
    domain: ToolDomain = ToolDomain.GENERAL
    allows_parallel: bool = False
    required_permissions: tuple[str, ...] = Field(default_factory=tuple)
    side_effect: ToolSideEffect | None = None
    retry_policy: ToolRetryPolicy | None = None
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    @model_validator(mode="after")
    def classify_execution_policy(self) -> "ToolDefinition":
        if self.side_effect is None:
            self.side_effect = {
                ToolRisk.READ: ToolSideEffect.NONE,
                ToolRisk.WRITE: (
                    ToolSideEffect.DRAFT
                    if self.name in {"create_invoice_draft", "update_invoice_draft"}
                    else ToolSideEffect.MUTATION
                ),
                ToolRisk.SENSITIVE: ToolSideEffect.MUTATION,
            }[self.risk]
        if self.retry_policy is None:
            self.retry_policy = (
                ToolRetryPolicy.SAFE_READ
                if self.risk == ToolRisk.READ
                else ToolRetryPolicy.IDEMPOTENCY_KEY
            )
        if self.risk == ToolRisk.READ and self.side_effect != ToolSideEffect.NONE:
            raise ValueError("read tools must declare side_effect='none'")
        if self.risk != ToolRisk.READ and self.side_effect == ToolSideEffect.NONE:
            raise ValueError("write tools must declare their side effects")
        if (
            self.risk == ToolRisk.READ
            and self.retry_policy != ToolRetryPolicy.SAFE_READ
        ):
            raise ValueError("read tools must use safe_read retry policy")
        if (
            self.risk != ToolRisk.READ
            and self.retry_policy == ToolRetryPolicy.SAFE_READ
        ):
            raise ValueError("write tools cannot use safe_read retry policy")
        return self

    @property
    def access_type(self) -> ToolAccessType:
        return (
            ToolAccessType.READ if self.risk == ToolRisk.READ else ToolAccessType.WRITE
        )

    @property
    def requires_confirmation(self) -> bool:
        return self.risk == ToolRisk.SENSITIVE


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Gemini 3 rejects the next tool round unless this is echoed back.
    # Excluded from API responses and persisted history.
    thought_signature: str | None = Field(default=None, exclude=True, max_length=16_384)


class ToolResult(BaseModel):
    """Validated, explicit outcome envelope shared by tools and chat clients."""

    tool: str
    success: bool
    data: dict[str, Any] | None = None
    result_status: ToolResultStatus | None = Field(
        default=None, serialization_alias="resultStatus"
    )
    applied_filters: dict[str, Any] | None = Field(
        default=None, serialization_alias="appliedFilters"
    )
    returned_count: int | None = Field(
        default=None, ge=0, serialization_alias="returnedCount"
    )
    total_count: int | None = Field(
        default=None, ge=0, serialization_alias="totalCount"
    )
    pagination: ToolPagination | None = None
    source: str | None = None
    source_timestamp: str | None = Field(
        default=None, serialization_alias="sourceTimestamp"
    )
    source_version: str | None = Field(
        default=None, serialization_alias="sourceVersion"
    )
    effect_status: ToolEffectStatus | None = Field(
        default=None, serialization_alias="effectStatus"
    )
    correlation_id: str | None = Field(
        default_factory=get_request_id, serialization_alias="correlationId"
    )

    @model_validator(mode="after")
    def complete_result_contract(self) -> "ToolResult":
        data = self.data or {}
        if self.result_status is None:
            self.result_status = _infer_result_status(self.success, data)
        if self.success != (self.result_status in _SUCCESS_STATUSES):
            raise ValueError("success must agree with resultStatus")
        if not self.success:
            self.data = _safe_failure_data(
                data, self.result_status, self.effect_status
            )

        if self.applied_filters is None:
            filters = data.get("appliedFilters", data.get("filters"))
            if isinstance(filters, dict):
                self.applied_filters = filters
        if self.returned_count is None:
            value = data.get("returnedCount", data.get("count"))
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self.returned_count = value
            elif self.result_status in {
                ToolResultStatus.SUCCESS_WITH_DATA,
                ToolResultStatus.SUCCESS_EMPTY,
                ToolResultStatus.SUCCESS_PARTIAL,
            }:
                rows = _primary_rows(data)
                if rows is not None:
                    self.returned_count = len(rows)
        if self.total_count is None:
            value = data.get("totalCount", data.get("totalRecords"))
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self.total_count = value
        pagination_data = data.get("pagination")
        meta = data.get("meta")
        if not isinstance(pagination_data, dict) and isinstance(meta, dict):
            pagination_data = meta.get("pagination")
        if self.pagination is None and isinstance(pagination_data, dict):
            self.pagination = ToolPagination.model_validate(pagination_data)
        if self.total_count is None and self.pagination is not None:
            pagination_payload = self.pagination.model_dump()
            value = pagination_payload.get("total_count")
            if isinstance(value, int) and value >= 0:
                self.total_count = value
        if self.source_timestamp is None:
            value = data.get("sourceTimestamp", data.get("asOf"))
            if isinstance(value, str):
                self.source_timestamp = value
        return self


_SUCCESS_STATUSES = {
    ToolResultStatus.SUCCESS_WITH_DATA,
    ToolResultStatus.SUCCESS_EMPTY,
    ToolResultStatus.SUCCESS_PARTIAL,
}


def _primary_rows(data: dict[str, Any]) -> list[Any] | None:
    for key in (
        "items",
        "invoices",
        "expenses",
        "customers",
        "suppliers",
        "orders",
        "staff",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _infer_result_status(success: bool, data: dict[str, Any]) -> ToolResultStatus:
    if success:
        if (
            data.get("partial") is True
            or data.get("truncated") is True
            or data.get("hasMore") is True
            or (
                isinstance(data.get("pagination"), dict)
                and data["pagination"].get("hasMore") is True
            )
            or (
                isinstance(data.get("coverage"), dict)
                and data["coverage"].get("complete") is False
            )
        ):
            return ToolResultStatus.SUCCESS_PARTIAL
        count = data.get("returnedCount", data.get("count", data.get("totalCount")))
        rows = _primary_rows(data)
        if count == 0 or data.get("found") is False or rows == [] or data == {}:
            return ToolResultStatus.SUCCESS_EMPTY
        return ToolResultStatus.SUCCESS_WITH_DATA

    code = str(data.get("code", "")).upper()
    if code in {"TOOL_UNSUPPORTED", "UNSUPPORTED_OPERATION"}:
        return ToolResultStatus.UNSUPPORTED
    if "INVALID" in code or "VALIDATION" in code or "DATE_RANGE" in code:
        return ToolResultStatus.INVALID_INPUT
    if "UNAUTHORIZED" in code or "FORBIDDEN" in code or "PERMISSION" in code:
        return ToolResultStatus.UNAUTHORIZED
    if code.endswith("NOT_FOUND") or code in {"NOT_FOUND", "TOOL_NOT_FOUND"}:
        return ToolResultStatus.NOT_FOUND
    if "TIMEOUT" in code:
        return ToolResultStatus.TIMEOUT
    if "RETAILER" in code or "DEPENDENCY" in code or "RATE_LIMITED" in code or not code:
        return ToolResultStatus.DEPENDENCY_ERROR
    return ToolResultStatus.INTERNAL_ERROR


def _safe_failure_data(
    data: dict[str, Any],
    status: ToolResultStatus,
    effect_status: ToolEffectStatus | None,
) -> dict[str, Any]:
    code = data.get("code")
    code = code if isinstance(code, str) else "TOOL_FAILED"
    message = data.get("message")
    if status == ToolResultStatus.INVALID_INPUT and isinstance(message, str):
        safe_message = message[:300]
    elif effect_status == ToolEffectStatus.UNKNOWN:
        safe_message = (
            "The request outcome could not be verified. "
            "Check the store before retrying."
        )
    else:
        safe_message = {
            ToolResultStatus.UNSUPPORTED: (
                "This operation is not supported in Drag AI."
            ),
            ToolResultStatus.UNAUTHORIZED: (
                "You do not have permission to complete this request."
            ),
            ToolResultStatus.NOT_FOUND: "No matching record was found.",
            ToolResultStatus.TIMEOUT: (
                "The request timed out; the result could not be verified."
            ),
            ToolResultStatus.DEPENDENCY_ERROR: (
                "Store data is temporarily unavailable; "
                "the result could not be verified."
            ),
            ToolResultStatus.INTERNAL_ERROR: (
                "The request could not be completed or verified."
            ),
        }.get(status, "The request could not be completed or verified.")
    return {"code": code, "message": safe_message}
