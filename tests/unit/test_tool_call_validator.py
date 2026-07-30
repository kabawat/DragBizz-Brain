import pytest

from app.core.exceptions import AppError
from app.orchestrator.tool_call_validator import ToolCallValidator
from app.schemas.tool import ToolCall
from app.tools.definitions import READ_TOOL_DEFINITIONS
from app.tools.registry import ToolRegistry

STORE_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def validator() -> ToolCallValidator:
    registry = ToolRegistry()
    for definition in READ_TOOL_DEFINITIONS:
        registry.register_definition(definition)
    return ToolCallValidator(registry)


def test_validator_accepts_allowlisted_tool(validator: ToolCallValidator) -> None:
    calls = validator.validate(
        [
            ToolCall(
                id="1",
                name="today_sale",
                arguments={"storeId": STORE_ID},
            )
        ],
        store_id=STORE_ID,
    )
    assert calls[0].name == "today_sale"


def test_validator_rejects_unknown_tool(validator: ToolCallValidator) -> None:
    with pytest.raises(AppError) as exc_info:
        validator.validate(
            [ToolCall(id="1", name="delete_store", arguments={})],
            store_id=STORE_ID,
        )
    assert exc_info.value.code == "TOOL_NOT_ALLOWED"


def test_validator_rejects_tool_outside_turn_allowlist(
    validator: ToolCallValidator,
) -> None:
    with pytest.raises(AppError) as exc_info:
        validator.validate(
            [
                ToolCall(
                    id="1",
                    name="today_sale",
                    arguments={"storeId": STORE_ID},
                )
            ],
            store_id=STORE_ID,
            allowed_names=frozenset({"stock_summary"}),
        )
    assert exc_info.value.code == "TOOL_NOT_ALLOWED"


def test_validator_accepts_tool_in_turn_allowlist(
    validator: ToolCallValidator,
) -> None:
    calls = validator.validate(
        [
            ToolCall(
                id="1",
                name="today_sale",
                arguments={"storeId": STORE_ID},
            )
        ],
        store_id=STORE_ID,
        allowed_names=frozenset({"today_sale"}),
    )
    assert calls[0].name == "today_sale"


def test_validator_rejects_invalid_args(validator: ToolCallValidator) -> None:
    with pytest.raises(AppError) as exc_info:
        validator.validate(
            [
                ToolCall(
                    id="1",
                    name="search_product",
                    arguments={"storeId": STORE_ID},
                )
            ],
            store_id=STORE_ID,
        )
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


def test_validator_rejects_mismatched_store_id(
    validator: ToolCallValidator,
) -> None:
    with pytest.raises(AppError) as exc_info:
        validator.validate(
            [
                ToolCall(
                    id="1",
                    name="today_sale",
                    arguments={"storeId": "aaaaaaaaaaaaaaaaaaaaaaaa"},
                )
            ],
            store_id=STORE_ID,
        )
    assert exc_info.value.code == "TOOL_ARGS_INVALID"
