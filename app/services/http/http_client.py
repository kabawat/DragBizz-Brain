from typing import Any, Dict

import requests
from fastapi import HTTPException
from requests import HTTPError, Response


class HttpClient:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def post(
        self,
        url: str,
        headers: Dict[str, str] | None = None,
        json: Dict[str, Any] | None = None,
        data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        try:
            response: Response = requests.post(
                url=url,
                headers=headers or {},
                json=json,
                data=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except HTTPError as http_err:
            resp = http_err.response
            detail = resp.text if resp is not None else str(http_err)
            status = resp.status_code if resp is not None else 500
            raise HTTPException(status_code=status, detail=detail) from http_err

        return response.json()
