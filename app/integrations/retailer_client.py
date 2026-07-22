from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.exceptions import AppError


@dataclass(frozen=True)
class RetailerResponse:
    status_code: int
    body: dict[str, Any]


class RetailerHttpError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class RetailerClient:
    def __init__(self, http_client: httpx.AsyncClient, base_url: str) -> None:
        self._http = http_client
        self._base_url = base_url.rstrip("/")

    async def get_products(
        self,
        *,
        access_token: str,
        store_id: str,
        query: str,
        limit: int = 20,
    ) -> RetailerResponse:
        return await self._get(
            "/product",
            access_token=access_token,
            store_id=store_id,
            params={"search": query, "limit": limit},
        )

    async def get_revenue(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._get(
            "/analytics/revenue",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_stock(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._get(
            "/analytics/stock",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_payments(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 20,
    ) -> RetailerResponse:
        return await self._get(
            "/customer-account/payments",
            access_token=access_token,
            store_id=store_id,
            params={"limit": limit},
        )

    async def _get(
        self,
        path: str,
        *,
        access_token: str,
        store_id: str,
        params: dict[str, Any] | None = None,
    ) -> RetailerResponse:
        query = {"store": store_id, **(params or {})}
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{self._base_url}{path}"

        try:
            response = await self._http.get(url, headers=headers, params=query)
        except httpx.TimeoutException as exc:
            raise RetailerHttpError(
                status_code=504,
                code="RETAILER_ERROR",
                message="Retailer request timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise RetailerHttpError(
                status_code=502,
                code="RETAILER_ERROR",
                message="Retailer request failed",
            ) from exc

        body = _safe_json(response)
        if response.status_code == 401:
            raise AppError(
                code="TOOL_UNAUTHORIZED",
                message="Retailer rejected the access token or store access",
                status_code=401,
            )
        if response.status_code >= 400:
            raise RetailerHttpError(
                status_code=response.status_code,
                code=_map_status_code(response.status_code),
                message=_error_message(body, response.status_code),
            )

        return RetailerResponse(status_code=response.status_code, body=body)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _map_status_code(status_code: int) -> str:
    if status_code == 403:
        return "TOOL_FORBIDDEN"
    if status_code == 404:
        return "TOOL_NOT_FOUND"
    if status_code == 429:
        return "TOOL_RATE_LIMITED"
    return "RETAILER_ERROR"


def _error_message(body: dict[str, Any], status_code: int) -> str:
    message = body.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return f"Retailer request failed with status {status_code}"
