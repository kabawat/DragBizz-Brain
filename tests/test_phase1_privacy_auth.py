"""Phase 1 regressions for signed store scope and permission minimization."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.chat import router as chat_router
from app.api.v1.sessions import router as sessions_router
from app.core.exceptions import AppError, register_exception_handlers
from app.core.security import get_current_user
from app.core.store_access import (
    authorized_store_entry,
    explicit_store_permissions,
    filter_tool_definitions,
)
from app.schemas.tool import ToolDefinition, ToolRisk
from app.tools.definitions import ALL_TOOL_DEFINITIONS, TOOL_PERMISSIONS

STORE_A = "a" * 24
STORE_B = "b" * 24


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "u1"},
        {"sub": "u1", "stores": []},
        {"sub": "u1", "stores": ["not-an-object-id"]},
    ],
)
def test_store_scope_fails_closed_for_missing_or_invalid_claims(claims: dict) -> None:
    with pytest.raises(AppError) as exc:
        authorized_store_entry(claims, STORE_A)
    assert exc.value.status_code == 403


def test_store_scope_rejects_user_selected_unclaimed_tenant() -> None:
    with pytest.raises(AppError) as exc:
        authorized_store_entry({"sub": "u1", "stores": [STORE_A]}, STORE_B)
    assert exc.value.code == "FORBIDDEN_STORE_ACCESS"


def test_store_scope_accepts_only_signed_claimed_store_and_permissions() -> None:
    user = {
        "sub": "u1",
        "stores": [
            {"storeId": STORE_A, "permissions": ["customers:read"]},
            {"storeId": STORE_B, "permissions": ["inventory:read"]},
        ],
    }
    assert authorized_store_entry(user, STORE_A)["storeId"] == STORE_A
    assert explicit_store_permissions(user, STORE_A) == frozenset({"customers:read"})


def test_unscoped_permissions_are_not_reused_across_multiple_stores() -> None:
    user = {
        "sub": "u1",
        "stores": [{"storeId": STORE_A}, {"storeId": STORE_B}],
        "permissions": ["customers:write"],
    }
    assert explicit_store_permissions(user, STORE_A) is None


def test_explicit_role_permissions_remove_unapproved_tools() -> None:
    definitions = (
        ToolDefinition(
            name="search_customer",
            description="read customers",
            risk=ToolRisk.READ,
            parameters={"type": "object"},
            required_permissions=("customers:read",),
        ),
        ToolDefinition(
            name="update_customer",
            description="write customers",
            risk=ToolRisk.WRITE,
            parameters={"type": "object"},
            required_permissions=("customers:write",),
        ),
    )
    filtered = filter_tool_definitions(definitions, frozenset({"customers:read"}))
    assert [item.name for item in filtered] == ["search_customer"]


def test_every_registered_tool_has_declared_permission_requirements() -> None:
    assert {definition.name for definition in ALL_TOOL_DEFINITIONS} == set(
        TOOL_PERMISSIONS
    )
    assert all(TOOL_PERMISSIONS.values())


@pytest.mark.asyncio
async def test_chat_and_session_routes_reject_cross_store_ids_before_access() -> None:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")

    class ChatServiceStub:
        async def handle(self, *_args, **_kwargs):
            raise AssertionError("unauthorized chat must not reach the service")

    app.state.chat_service = ChatServiceStub()
    app.state.retailer_client = object()
    register_exception_handlers(app)

    async def user_claims():
        return {"sub": "u1", "stores": [STORE_A]}

    @app.middleware("http")
    async def attach_test_token(request, call_next):
        request.state.access_token = "signed-test-token"
        return await call_next(request)

    app.dependency_overrides[get_current_user] = user_claims
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        responses = [
            await client.post(
                "/api/v1/chat",
                json={"text": "hello", "sessionId": "s1", "storeId": STORE_B},
            ),
            await client.post(
                "/api/v1/chat/stream",
                json={"text": "hello", "sessionId": "s1", "storeId": STORE_B},
            ),
            await client.post(
                "/api/v1/chat/confirm",
                json={
                    "sessionId": "s1",
                    "storeId": STORE_B,
                    "confirmationId": "c" * 24,
                    "draftId": "d" * 24,
                    "action": "reject",
                },
            ),
            await client.get("/api/v1/chat/sessions", params={"storeId": STORE_B}),
            await client.get("/api/v1/chat/sessions/s1", params={"storeId": STORE_B}),
            await client.delete(
                "/api/v1/chat/sessions/s1", params={"storeId": STORE_B}
            ),
        ]
    assert [response.status_code for response in responses] == [403] * 6
