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

    async def get_variants(
        self,
        *,
        access_token: str,
        store_id: str,
        product_id: str,
        limit: int = 20,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/variant",
            access_token=access_token,
            store_id=store_id,
            params={
                "product": product_id,
                "limit": min(max(limit, 1), 50),
                "lightweight": "true",
            },
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

    async def get_customer_detailed_analytics(
        self,
        *,
        access_token: str,
        store_id: str,
        period_days: int,
        analytics_type: str = "overview",
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/customers/detailed",
            access_token=access_token,
            store_id=store_id,
            params={"period": str(period_days), "type": analytics_type},
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

    async def get_stock_items(
        self,
        *,
        access_token: str,
        store_id: str,
        include_services: bool = False,
    ) -> RetailerResponse:
        params: dict[str, Any] = {}
        if include_services:
            params["includeServices"] = "true"
        return await self._request(
            "GET",
            "/analytics/stock/items",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_product_analytics(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/products",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_inventory(
        self,
        *,
        access_token: str,
        store_id: str,
        product_id: str,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/stock",
            access_token=access_token,
            store_id=store_id,
            params={"product": product_id, "limit": 1},
        )

    async def add_stock(
        self,
        *,
        access_token: str,
        store_id: str,
        product_id: str,
        quantity: float,
        purchase_price: float,
        idempotency_key: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {
            "productId": product_id,
            "batchData": {
                "quantity": quantity,
                "purchasePrice": purchase_price,
            },
        }
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
            body["clientLocalId"] = idempotency_key
        return await self._request(
            "POST",
            "/stock",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def get_payments(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 20,
        customer_id: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if customer_id is not None:
            params["customerId"] = customer_id
        return await self._request(
            "GET",
            "/customer-account/payments",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_payment(
        self,
        *,
        access_token: str,
        store_id: str,
        payment_id: str,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            f"/customer-account/payments/{payment_id}",
            access_token=access_token,
            store_id=store_id,
        )

    async def create_customer_payment(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        payment_type: str,
        payment: list[dict[str, Any]],
        invoice: str | None = None,
        invoice_allocations: list[dict[str, Any]] | None = None,
        allocate_to_invoices: bool | None = None,
        notes: str | None = None,
        idempotency_key: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {
            "customer": customer_id,
            "paymentType": payment_type,
            "payment": payment,
        }
        if invoice is not None:
            body["invoice"] = invoice
        if invoice_allocations is not None:
            body["invoiceAllocations"] = invoice_allocations
        if allocate_to_invoices is not None:
            body["allocateToInvoices"] = allocate_to_invoices
        if notes is not None:
            body["notes"] = notes
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key
        return await self._request(
            "POST",
            "/customer-account/payments",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def update_customer_payment(
        self,
        *,
        access_token: str,
        store_id: str,
        payment_id: str,
        notes: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {}
        if notes is not None:
            body["notes"] = notes
        return await self._request(
            "PUT",
            f"/customer-account/payments/{payment_id}",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def create_collect_link(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        amount: float | None = None,
        notes: str | None = None,
        description: str | None = None,
        allocate_to_invoices: bool | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"customer": customer_id}
        if amount is not None:
            body["amount"] = amount
        if notes is not None:
            body["notes"] = notes
        if description is not None:
            body["description"] = description
        if allocate_to_invoices is not None:
            body["allocateToInvoices"] = allocate_to_invoices
        return await self._request(
            "POST",
            "/customer-account/payments/collect-link",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def create_payment_reminder(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        channel: str | None = None,
        include_payment_link: bool | None = None,
        notes: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"customer": customer_id}
        if channel is not None:
            body["channel"] = channel
        if include_payment_link is not None:
            body["includePaymentLink"] = include_payment_link
        if notes is not None:
            body["notes"] = notes
        return await self._request(
            "POST",
            "/customer-account/reminders",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def list_payment_reminders(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str | None = None,
        limit: int = 20,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if customer_id is not None:
            params["customerId"] = customer_id
        return await self._request(
            "GET",
            "/customer-account/reminders",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_customer_ledger(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        limit: int = 50,
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            f"/customer-account/{customer_id}/ledger",
            access_token=access_token,
            store_id=store_id,
            params={"limit": limit},
        )

    async def list_customer_accounts(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str | None = None,
        has_due: bool | None = None,
        limit: int = 20,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if customer_id is not None:
            params["customerId"] = customer_id
        if has_due is not None:
            params["hasDue"] = "true" if has_due else "false"
        return await self._request(
            "GET",
            "/customer-account",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def create_customer_account(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        total_due: float | None = None,
        total_paid: float | None = None,
        total_amount: float | None = None,
        notes: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"customer": customer_id}
        if total_due is not None:
            body["totalDue"] = total_due
        if total_paid is not None:
            body["totalPaid"] = total_paid
        if total_amount is not None:
            body["totalAmount"] = total_amount
        if notes is not None:
            body["notes"] = notes
        return await self._request(
            "POST",
            "/customer-account/",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def get_invoices(
        self,
        *,
        access_token: str,
        store_id: str,
        customer_id: str,
        limit: int = 10,
        include_items: bool = True,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"customer": customer_id, "limit": limit}
        if include_items:
            params["includeItems"] = "true"
        return await self._request(
            "GET",
            "/invoices",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def list_invoices(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 100,
        invoice_status: str | None = "RELEASED",
        payment_status: str | None = None,
        customer_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_items: bool = False,
        next_cursor: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {
            "limit": limit,
            "includeItems": "true" if include_items else "false",
        }
        if invoice_status:
            params["invoiceStatus"] = invoice_status
        if payment_status:
            params["paymentStatus"] = payment_status
        if customer_id:
            params["customer"] = customer_id
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if next_cursor:
            params["nextCursor"] = next_cursor
        return await self._request(
            "GET",
            "/invoices",
            access_token=access_token,
            store_id=store_id,
            params=params,
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
        next_cursor: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if query.strip():
            params["search"] = query
        if next_cursor:
            params["nextCursor"] = next_cursor
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

    async def verify_store_access(
        self,
        *,
        access_token: str,
        store_id: str,
        agency_id: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"id": store_id}
        if agency_id:
            params["agency"] = agency_id
        return await self._request(
            "GET",
            "/store",
            access_token=access_token,
            store_id=store_id,
            params=params,
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
        note: str | None = None,
        company_details: dict[str, Any] | None = None,
        addresses: dict[str, Any] | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"store": store_id, "name": name}
        if phone is not None:
            body["phone"] = phone
        if email is not None:
            body["email"] = email
        if note is not None:
            body["note"] = note
        if company_details is not None:
            body["companyDetails"] = company_details
        if addresses is not None:
            body["addresses"] = addresses
        return await self._request(
            "PUT",
            f"/customer/{customer_id}",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def merge_customers(
        self,
        *,
        access_token: str,
        store_id: str,
        primary_id: str,
        duplicate_id: str,
        field_overrides: dict[str, Any] | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {
            "primaryId": primary_id,
            "duplicateId": duplicate_id,
        }
        if field_overrides is not None:
            body["fieldOverrides"] = field_overrides
        return await self._request(
            "POST",
            "/customer/merge",
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
        idempotency_key: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {"items": items, "isWalkin": is_walkin}
        if customer_id is not None:
            body["customer"] = customer_id
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
            body["clientLocalId"] = idempotency_key
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

    async def get_expense_analytics(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/expenses",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_expenses(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 20,
        category: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET",
            "/expense",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def create_expense(
        self,
        *,
        access_token: str,
        store_id: str,
        title: str,
        amount: float,
        category: str,
        date: str | None = None,
        payment_mode: str | None = None,
        notes: str | None = None,
        description: str | None = None,
        status: str | None = None,
        idempotency_key: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {
            "title": title,
            "amount": amount,
            "category": category,
        }
        if date:
            body["date"] = date
        if payment_mode:
            body["paymentMode"] = payment_mode
        if status:
            body["status"] = status
        desc_val = description or notes
        if desc_val:
            body["description"] = desc_val
            body["notes"] = desc_val
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
            body["clientLocalId"] = idempotency_key
        return await self._request(
            "POST",
            "/expense",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def update_expense(
        self,
        *,
        access_token: str,
        store_id: str,
        expense_id: str,
        title: str | None = None,
        amount: float | None = None,
        category: str | None = None,
        date: str | None = None,
        payment_mode: str | None = None,
        notes: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> RetailerResponse:
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if amount is not None:
            body["amount"] = amount
        if category is not None:
            body["category"] = category
        if date is not None:
            body["date"] = date
        if payment_mode is not None:
            body["paymentMode"] = payment_mode
        if status is not None:
            body["status"] = status
        desc_val = description if description is not None else notes
        if desc_val is not None:
            body["description"] = desc_val
            body["notes"] = desc_val
        return await self._request(
            "PUT",
            f"/expense/{expense_id}",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )


    async def get_cashbook_summary(
        self,
        *,
        access_token: str,
        store_id: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return await self._request(
            "GET",
            "/cashbook/summary",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_suppliers(
        self,
        *,
        access_token: str,
        store_id: str,
        query: str = "",
        limit: int = 20,
        include_account: bool = False,
        next_cursor: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if query.strip():
            params["search"] = query.strip()
        if include_account:
            params["includeAccount"] = "true"
        if next_cursor:
            params["nextCursor"] = next_cursor
        return await self._request(
            "GET",
            "/supplier",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_supplier_analytics(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/suppliers",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_purchase_orders(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 20,
        status: str | None = None,
        supplier_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        cursor: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if supplier_id:
            params["supplier"] = supplier_id
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET",
            "/purchase-order",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_supplier_bills(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 20,
        status: str | None = None,
        payment_status: str | None = None,
        supplier_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        search: str | None = None,
        next_cursor: str | None = None,
    ) -> RetailerResponse:
        """Fetch supplier bills from their domain endpoint, never purchase orders."""
        params: dict[str, Any] = {"limit": limit, "lightweight": "true"}
        if status:
            params["status"] = status
        if payment_status:
            params["paymentStatus"] = payment_status
        if supplier_id:
            params["supplier"] = supplier_id
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if search:
            params["search"] = search
        if next_cursor:
            params["nextCursor"] = next_cursor
        return await self._request(
            "GET",
            "/supplier-account/bills",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def create_purchase_order(
        self,
        *,
        access_token: str,
        store_id: str,
        supplier_id: str,
        items: list[dict[str, Any]],
        payment_terms: str | None = None,
        payment_by: str | None = None,
        reference: str | None = None,
        notes: str | None = None,
        expected_delivery_date: str | None = None,
        advance_amount: float | None = None,
        idempotency_key: str | None = None,
    ) -> RetailerResponse:
        products = [
            {
                "product": item.get("productId") or item.get("product"),
                "quantity": item.get("quantity", 0),
            }
            for item in items
        ]
        body: dict[str, Any] = {
            "supplier": supplier_id,
            "products": products,
        }
        if payment_terms:
            body["paymentTerms"] = payment_terms
        if payment_by:
            body["paymentBy"] = payment_by
        if reference:
            body["reference"] = reference
        if notes:
            body["note"] = notes
            body["notes"] = notes
        if expected_delivery_date:
            body["expectedDeliveryDate"] = expected_delivery_date
        if advance_amount is not None:
            body["advanceAmount"] = advance_amount
        if idempotency_key:
            body["idempotencyKey"] = idempotency_key
            body["clientLocalId"] = idempotency_key
        return await self._request(
            "POST",
            "/purchase-order",
            access_token=access_token,
            store_id=store_id,
            json_body=body,
        )

    async def get_bill_analytics(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/analytics/bills",
            access_token=access_token,
            store_id=store_id,
        )

    async def get_gst_summary(
        self,
        *,
        access_token: str,
        store_id: str,
        month: str | None = None,
        quarter: str | None = None,
        year: str | None = None,
        period: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {}
        if month:
            params["month"] = month
        if quarter:
            params["quarter"] = quarter
        if year:
            params["year"] = year
        if period:
            params["period"] = period
        return await self._request(
            "GET",
            "/gst/summary",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_gst_health_score(
        self,
        *,
        access_token: str,
        store_id: str,
        month: str | None = None,
        quarter: str | None = None,
        year: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {}
        if month:
            params["month"] = month
        if quarter:
            params["quarter"] = quarter
        if year:
            params["year"] = year
        return await self._request(
            "GET",
            "/gst/health-score",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_sales_orders(
        self,
        *,
        access_token: str,
        store_id: str,
        limit: int = 20,
        status: str | None = None,
        customer_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        next_cursor: str | None = None,
    ) -> RetailerResponse:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if customer_id:
            params["customer"] = customer_id
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if next_cursor:
            params["nextCursor"] = next_cursor
        return await self._request(
            "GET",
            "/sales-order",
            access_token=access_token,
            store_id=store_id,
            params=params,
        )

    async def get_staff(
        self, *, access_token: str, store_id: str
    ) -> RetailerResponse:
        return await self._request(
            "GET",
            "/staff",
            access_token=access_token,
            store_id=store_id,
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
