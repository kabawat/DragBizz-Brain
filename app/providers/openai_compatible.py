from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import Settings
from app.core.exceptions import AppError
from app.providers.base import ModelProvider
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition


class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    @property
    def name(self) -> str:
        return "openai_compatible"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not self._settings.openai_api_key:
            raise AppError(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="OpenAI API key is not configured",
                status_code=503,
            )

        payload: dict[str, Any] = {
            "model": self._settings.openai_model,
            "messages": [
                _to_openai_message(message) for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [_to_openai_tool(tool) for tool in request.tools]
            payload["tool_choice"] = request.tool_choice

        url = f"{self._settings.openai_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.openai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._http.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._settings.provider_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request timed out",
                status_code=502,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request failed",
                status_code=502,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request failed",
                status_code=502,
            ) from exc
        except ValueError as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider returned invalid JSON",
                status_code=502,
            ) from exc

        return _parse_completion(body, provider_name=self.name)


def _to_openai_message(message: ChatMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "content": message.content,
        }

    payload: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }
    if message.role == "assistant" and message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _to_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_completion(
    body: dict[str, Any], *, provider_name: str
) -> GenerationResponse:
    try:
        choice = body["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError(
            code="AI_PROVIDER_ERROR",
            message="AI provider returned an unexpected response",
            status_code=502,
        ) from exc

    content = message.get("content") or ""
    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[ToolCall] = []
    for raw in raw_tool_calls:
        try:
            function = raw["function"]
            arguments = _parse_arguments(function.get("arguments", "{}"))
            tool_calls.append(
                ToolCall(
                    id=str(raw.get("id") or function["name"]),
                    name=function["name"],
                    arguments=arguments,
                )
            )
        except AppError:
            raise
        except (KeyError, TypeError) as exc:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Provider returned malformed tool call arguments",
                status_code=400,
            ) from exc

    usage = body.get("usage") or {}
    return GenerationResponse(
        provider=provider_name,
        model=str(body.get("model") or ""),
        content=content if isinstance(content, str) else str(content),
        tool_calls=tool_calls,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )


def _parse_arguments(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool arguments must be a JSON object",
            status_code=400,
        )
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool arguments must be valid JSON",
            status_code=400,
        ) from exc
    if not isinstance(parsed, dict):
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool arguments must be a JSON object",
            status_code=400,
        )
    return parsed
