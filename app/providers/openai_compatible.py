from __future__ import annotations

import json
import ssl
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings
from app.core.exceptions import AppError
from app.providers.base import ModelProvider
from app.schemas.chat import ChatMessage, GenerationRequest, GenerationResponse
from app.schemas.tool import ToolCall, ToolDefinition

OPENAI_PROVIDER_NAME = "openai_compatible"
GOOGLE_PROVIDER_NAME = "google_ai"
CHEAPER_PROVIDER_NAME = "cheaper_inference"

# Statuses that mean the provider did not return a usable completion.
_UNAVAILABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})


class OpenAICompatibleProvider(ModelProvider):
    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
        *,
        name: str = OPENAI_PROVIDER_NAME,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self._name = name
        self._http = http_client
        self._api_key = settings.openai.api_key if api_key is None else api_key
        self._base_url = (base_url or settings.openai.base_url).rstrip("/")
        self._default_model = default_model or settings.openai.model
        self._timeout = settings.chat.provider_timeout_seconds

    @property
    def name(self) -> str:
        return self._name

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not self._api_key:
            raise AppError(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="AI provider API key is not configured",
                status_code=503,
            )

        payload: dict[str, Any] = {
            "model": request.model or self._default_model,
            "messages": [_to_openai_message(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.tools:
            payload["tools"] = [_to_openai_tool(tool) for tool in request.tools]
            payload["tool_choice"] = request.tool_choice

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._http.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
        except httpx.TimeoutException as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request timed out",
                status_code=502,
                retryable=True,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            # Status only — never log response body (may contain provider details).
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message=f"AI provider request failed (HTTP {status})",
                status_code=502,
                retryable=status in _UNAVAILABLE_STATUS,
            ) from exc
        except (httpx.HTTPError, ssl.SSLError) as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request failed",
                status_code=502,
                retryable=True,
            ) from exc
        except ValueError as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider returned invalid JSON",
                status_code=502,
            ) from exc

        return _parse_completion(body, provider_name=self.name)

    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[str]:
        if not self._api_key:
            raise AppError(
                code="AI_PROVIDER_NOT_CONFIGURED",
                message="AI provider API key is not configured",
                status_code=503,
            )

        payload: dict[str, Any] = {
            "model": request.model or self._default_model,
            "messages": [_to_openai_message(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        if request.tools:
            payload["tools"] = [_to_openai_tool(tool) for tool in request.tools]
            payload["tool_choice"] = request.tool_choice

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with self._http.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    status = (
                        exc.response.status_code if exc.response is not None else None
                    )
                    raise AppError(
                        code="AI_PROVIDER_ERROR",
                        message=f"AI provider request failed (HTTP {status})",
                        status_code=502,
                        retryable=status in _UNAVAILABLE_STATUS,
                    ) from exc
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                    else:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = _stream_delta_text(chunk)
                    if delta:
                        yield delta
        except AppError:
            raise
        except httpx.TimeoutException as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request timed out",
                status_code=502,
                retryable=True,
            ) from exc
        except (httpx.HTTPError, ssl.SSLError) as exc:
            raise AppError(
                code="AI_PROVIDER_ERROR",
                message="AI provider request failed",
                status_code=502,
                retryable=True,
            ) from exc


def _stream_delta_text(chunk: dict[str, Any]) -> str:
    try:
        choice = chunk["choices"][0]
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            return content
    except (KeyError, IndexError, TypeError):
        return ""
    return ""


def build_google_provider(
    settings: Settings, http_client: httpx.AsyncClient
) -> OpenAICompatibleProvider | None:
    if not settings.google.api_key:
        return None
    return OpenAICompatibleProvider(
        settings,
        http_client,
        name=GOOGLE_PROVIDER_NAME,
        api_key=settings.google.api_key,
        base_url=settings.google.base_url,
        default_model=settings.google.model,
    )


def build_cheaper_provider(
    settings: Settings, http_client: httpx.AsyncClient
) -> OpenAICompatibleProvider | None:
    if not settings.cheaper_inference.api_key:
        return None
    return OpenAICompatibleProvider(
        settings,
        http_client,
        name=CHEAPER_PROVIDER_NAME,
        api_key=settings.cheaper_inference.api_key,
        base_url=settings.cheaper_inference.base_url,
        default_model=settings.cheaper_inference.model,
    )


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
            _to_openai_tool_call(call) for call in message.tool_calls
        ]
    return payload


def _to_openai_tool_call(call: ToolCall) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.arguments, ensure_ascii=False),
        },
    }
    if call.thought_signature:
        payload["extra_content"] = {
            "google": {"thought_signature": call.thought_signature}
        }
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
    parse_failures = 0
    for raw in raw_tool_calls:
        try:
            function = raw["function"]
            arguments = _parse_arguments(function.get("arguments", "{}"))
            tool_calls.append(
                ToolCall(
                    id=str(raw.get("id") or function["name"]),
                    name=function["name"],
                    arguments=arguments,
                    thought_signature=_thought_signature(raw),
                )
            )
        except AppError:
            parse_failures += 1
            continue
        except (KeyError, TypeError):
            parse_failures += 1
            continue

    # Only fail hard when every tool call was unusable and there was no text.
    if (
        raw_tool_calls
        and not tool_calls
        and parse_failures > 0
        and not (isinstance(content, str) and content.strip())
    ):
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool arguments must be valid JSON",
            status_code=400,
        )

    usage = body.get("usage") or {}
    return GenerationResponse(
        provider=provider_name,
        model=str(body.get("model") or ""),
        content=content if isinstance(content, str) else str(content),
        tool_calls=tool_calls,
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )


def _thought_signature(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    extra = raw.get("extra_content")
    if not isinstance(extra, dict):
        return None
    google = extra.get("google")
    if not isinstance(google, dict):
        return None
    signature = google.get("thought_signature")
    if isinstance(signature, str) and signature:
        return signature
    return None


def _parse_arguments(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool arguments must be a JSON object",
            status_code=400,
        )
    text = raw.strip() if raw else ""
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        repaired = _repair_json_object(text)
        if repaired is None:
            raise AppError(
                code="TOOL_ARGS_INVALID",
                message="Tool arguments must be valid JSON",
                status_code=400,
            ) from exc
        parsed = repaired
    if not isinstance(parsed, dict):
        raise AppError(
            code="TOOL_ARGS_INVALID",
            message="Tool arguments must be a JSON object",
            status_code=400,
        )
    return parsed


def _repair_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort fix for truncated / trailing-comma tool argument JSON."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].strip()
    stack: list[str] = []
    cleaned_chars: list[str] = []
    in_string = False
    escape = False
    for ch in candidate:
        if in_string:
            cleaned_chars.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            cleaned_chars.append(ch)
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
            cleaned_chars.append(ch)
            continue
        if ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            cleaned_chars.append(ch)
            continue
        cleaned_chars.append(ch)
    if in_string:
        if escape:
            cleaned_chars.append("\\")
        cleaned_chars.append('"')
    cleaned = "".join(cleaned_chars) + "".join(reversed(stack))
    cleaned = cleaned.replace(",}", "}").replace(",]", "]")
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
