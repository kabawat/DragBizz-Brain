from __future__ import annotations

import httpx

from app.config import Settings
from app.core.exceptions import AppError

EMBEDDING_BATCH_SIZE = 100


class EmbeddingService:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._settings.openai.api_key:
            raise AppError(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="OpenAI API key is not configured",
                status_code=503,
            )

        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        url = f"{self._settings.openai.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._settings.openai.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._settings.rag.embedding_model,
            "input": batch,
        }

        try:
            response = await self._http.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._settings.chat.provider_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="Embedding request timed out",
                status_code=502,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="Embedding request failed",
                status_code=502,
            ) from exc
        except ValueError as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="Embedding provider returned invalid JSON",
                status_code=502,
            ) from exc

        return _parse_embeddings(body, expected=len(batch))


def _parse_embeddings(body: object, *, expected: int) -> list[list[float]]:
    try:
        items = sorted(body["data"], key=lambda item: item["index"])
        vectors = [item["embedding"] for item in items]
    except (KeyError, TypeError) as exc:
        raise AppError(
            code="AI_PROVIDER_ERROR",
            message="Embedding provider returned an unexpected response",
            status_code=502,
        ) from exc

    if len(vectors) != expected or not all(
        isinstance(vector, list) for vector in vectors
    ):
        raise AppError(
            code="AI_PROVIDER_ERROR",
            message="Embedding provider returned an unexpected response",
            status_code=502,
        )
    return vectors
