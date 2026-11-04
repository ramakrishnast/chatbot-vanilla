"""Thin async client for the parts of the Ollama HTTP API this app uses."""

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.schemas import ModelInfo

log = logging.getLogger(__name__)

ChatHistory = list[dict[str, str]]


class OllamaError(Exception):
    """Ollama could not be reached or rejected the request."""


@dataclass(frozen=True)
class ChatChunk:
    content: str = ""
    thinking: str = ""


class LLMClient(Protocol):
    """What the routers need from an LLM backend; tests substitute a fake."""

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]: ...

    async def ping(self) -> bool: ...

    def stream_chat(
        self, model: str, messages: ChatHistory, *, think: bool | None = None
    ) -> AsyncIterator[ChatChunk]: ...

    async def complete(
        self, model: str, messages: ChatHistory, *, think: bool | None = None
    ) -> str: ...

    async def aclose(self) -> None: ...


def _error_text(response: httpx.Response, body: bytes) -> str:
    try:
        return str(json.loads(body)["error"])
    except (ValueError, KeyError, TypeError):
        return f"Ollama returned HTTP {response.status_code}"


class OllamaClient:
    MODELS_CACHE_SECONDS = 30.0

    def __init__(self, base_url: str, timeout: float) -> None:
        # `read` is the gap allowed between streamed tokens (large models can be slow to load).
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout, connect=5.0)
        )
        self._models: list[ModelInfo] = []
        self._models_at = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def ping(self) -> bool:
        try:
            response = await self._client.get("/api/version", timeout=3.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        fresh = time.monotonic() - self._models_at < self.MODELS_CACHE_SECONDS
        if self._models and fresh and not refresh:
            return self._models
        try:
            response = await self._client.get("/api/tags", timeout=10.0)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Could not reach Ollama: {exc}") from exc
        if response.status_code != 200:
            raise OllamaError(_error_text(response, response.content))
        models = []
        for raw in response.json().get("models", []):
            details = raw.get("details") or {}
            models.append(
                ModelInfo(
                    name=raw["name"],
                    size=raw.get("size"),
                    parameter_size=details.get("parameter_size"),
                    family=details.get("family"),
                    capabilities=raw.get("capabilities") or [],
                )
            )
        models.sort(key=lambda m: m.name)
        self._models, self._models_at = models, time.monotonic()
        return models

    def _payload(
        self, model: str, messages: ChatHistory, *, stream: bool, think: bool | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if think is not None:
            payload["think"] = think
        return payload

    async def stream_chat(
        self, model: str, messages: ChatHistory, *, think: bool | None = None
    ) -> AsyncIterator[ChatChunk]:
        payload = self._payload(model, messages, stream=True, think=think)
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    raise OllamaError(_error_text(response, await response.aread()))
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise OllamaError(str(data["error"]))
                    message = data.get("message") or {}
                    chunk = ChatChunk(
                        content=message.get("content") or "",
                        thinking=message.get("thinking") or "",
                    )
                    if chunk.content or chunk.thinking:
                        yield chunk
                    if data.get("done"):
                        return
        except httpx.HTTPError as exc:
            raise OllamaError(f"Could not reach Ollama: {exc}") from exc

    async def complete(
        self, model: str, messages: ChatHistory, *, think: bool | None = None
    ) -> str:
        payload = self._payload(model, messages, stream=False, think=think)
        try:
            response = await self._client.post("/api/chat", json=payload)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Could not reach Ollama: {exc}") from exc
        if response.status_code != 200:
            raise OllamaError(_error_text(response, response.content))
        return str((response.json().get("message") or {}).get("content") or "")
