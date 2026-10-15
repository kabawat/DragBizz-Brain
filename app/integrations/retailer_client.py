from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.exceptions import AppError

HttpMethod = Literal["GET", "POST", "PUT"]


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
        return await self._request(
            "GET",
            "/product",
            access_token=access_token,
            store_id=store_id,
            params={"search": query, "limit": limit},
        )

    async def get_revenue(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/revenue",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_customer_analytics(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/customers",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_invoice_analytics(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/invoices",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_invoice_detailed_analytics(
        self,
        *,
        access_token: str,
        store_id: str,
        period_days: int,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/invoices/detailed",
            access_token=access_token,
            store_id=store_id,
            params={"period": str(period_days)},
        )

    async def get_stock(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
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
        return await self._request(
            "GET",
            "/customer-account/payments",
            access_token=access_token,
            store_id=store_id,
            params={"limit": limit},
        )

    async def get_customers(
        self,
        *,
        access_token: str,
        store_id: str,
        query: str,
        limit: int = 10,
        include_addresses: bool = False,
        include_account: bool = False,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"search": query, "limit": limit}
        if include_addresses:
            params["includeAddresses"] = "true"
        if include_account:
            params["includeAccount"] = "true"
        return await self._request(
            "GET",
            "/customer",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_customer_ledger_export(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            f"/customer-account/{customer_id}/ledger/export",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_stores(
        self,
        *,
        access_token: str,
        store_id: str,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/store",
            access_token=access_token,
            store_id=store_id,
        )

    async def create_customer(
        self,
        *,
        access_token: str,
        store_id: str,
        name: str,
        phone: str | None = None,
        email: str | None = None,
        source: str = "VOICE_AI",
    ) -> RetailerResponse:
        body: dict[str, Any] = {
            "store": store_id,
            "name": name,
            "source": source,
        }
        if phone is not None:
            body["phone"] = phone
        if email is not None:
            body["email"] = email
        return await self._request(
            "POST",
            "/customer",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def update_customer(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        name: str,
        phone: str | None = None,
        email: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"store": store_id, "name": name}
        if phone is not None:
            body["phone"] = phone
        if email is not None:
            body["email"] = email
        return await self._request(
            "PUT",
            f"/customer/{customer_id}",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def create_invoice_draft(
        self,
        *,
        access_token: str,
        store_id: str,
        items: list[dict[str, Any]],
        customer_id: str | None = None,
        is_walkin: bool = False,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"items": items, "isWalkin": is_walkin}
        if customer_id is not None:
            body["customer"] = customer_id
        return await self._request(
            "POST",
            "/invoices",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def update_invoice_draft(
        self,
        *,
        access_token: str,
        store_id: str,
        invoice_id: str,
        customer_id: str | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {}
        if customer_id is not None:
            body["customer"] = customer_id
        if items is not None:
            body["items"] = items
        return await self._request(
            "PUT",
            f"/invoices/{invoice_id}",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def release_invoice(
        self,
        *,
        access_token: str,
        store_id: str,
        invoice_id: str,
        payment_status: str | None = None,
        paid_amount: float | None = None,
        payment_mode: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"id": invoice_id}
        if payment_status is not None:
            body["paymentStatus"] = payment_status
        if paid_amount is not None:
            body["paidAmount"] = paid_amount
        if payment_mode is not None:
            body["paymentMode"] = payment_mode
        return await self._request(
            "POST",
            "/invoices/release",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def create_ledger_transaction(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        transaction_type: Literal["PAYMENT", "DEBIT"],
        amount: float,
        idempotency_key: str,
        payment_mode: str | None = None,
        notes: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {
            "customer": customer_id,
            "type": transaction_type,
            "amount": amount,
            "idempotencyKey": idempotency_key,
            "source": "MANUAL",
        }
        if payment_mode is not None:
            body["paymentMode"] = payment_mode
        if notes is not None:
            body["notes"] = notes
        return await self._request(
            "POST",
            "/customer-account/transactions",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        access_token: str,
        store_id: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> RetailerResponse:
        query = {"store": store_id, **(params or {})}
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{self._base_url}{path}"

        try:
            response = await self._http.request(
                method,
                url,
                headers=headers,
                params=query,
                json=json_body,
            )
        except httpx.TimeoutException as exc:
            raise RetailerHttpError(
                status_code=504,
                code="RETAILER_TIMEOUT",
                message="Retailer request timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise RetailerHttpError(
                status_code=502,
                code="RETAILER_UNAVAILABLE",
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
    if status_code == 409:
        return "TOOL_CONFLICT"
    if status_code == 429:
        return "TOOL_RATE_LIMITED"
    return "RETAILER_ERROR"


def _error_message(body: dict[str, Any], status_code: int) -> str:
    message = body.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return f"Retailer request failed with status {status_code}"
