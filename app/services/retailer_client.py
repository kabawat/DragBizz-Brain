"""Retailer API client for Voice-AI service-to-service calls.

Uses Bearer JWT + X-Internal-Secret for secure authentication.
Token is forwarded from the incoming request (user's cookie).
"""
from typing import Any

from app.config.settings import get_settings
from app.services.http import HttpClient


class RetailerClient:
    """HTTP client for calling Retailer API with internal service auth."""

    def __init__(self, timeout: int = 10):
        self.settings = get_settings()
        self.http_client = HttpClient(timeout=timeout)

    def _build_headers(self, token: str) -> dict[str, str]:
        """Build auth headers for Retailer API (IP whitelist + Bearer + X-Internal-Secret)."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if self.settings.internal_service_secret:
            headers["X-Internal-Secret"] = self.settings.internal_service_secret
        return headers

    async def get(
        self,
        path: str,
        token: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET request to Retailer API."""
        url = f"{self.settings.retailer_url.rstrip('/')}{path}"
        headers = self._build_headers(token)
        return await self.http_client.get(url, headers=headers, params=params or {})

    async def post(
        self,
        path: str,
        token: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST request to Retailer API."""
        url = f"{self.settings.retailer_url.rstrip('/')}{path}"
        headers = self._build_headers(token)
        return await self.http_client.post(url, headers=headers, json=json_data or {})

