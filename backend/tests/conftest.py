import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import BACKEND_DIR, Settings
from app.db import create_engine, create_sessionmaker
from app.main import create_app
from app.ollama import ChatChunk, ChatHistory, OllamaError
from app.schemas import ModelInfo


class FakeLLM:
    """Stands in for Ollama: scripted chunks, optional mid-stream failure, recorded calls."""

    def __init__(self) -> None:
        self.models = [
            ModelInfo(name="fake-chat:1b", capabilities=["completion"]),
            ModelInfo(name="fake-thinker:4b", capabilities=["completion", "thinking"]),
            ModelInfo(name="nomic-embed-text:latest", capabilities=["embedding"]),
        ]
        self.chunks = [ChatChunk(content="Hello"), ChatChunk(content=" there")]
        self.fail_after_chunks: str | None = None
        self.title = "Friendly Greeting"
        self.healthy = True
        self.calls: list[dict[str, Any]] = []

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        return self.models

    async def ping(self) -> bool:
        return self.healthy

    async def stream_chat(
        self, model: str, messages: ChatHistory, *, think: bool | None = None
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append({"model": model, "messages": messages, "think": think})
        for chunk in self.chunks:
            yield chunk
        if self.fail_after_chunks:
            raise OllamaError(self.fail_after_chunks)

    async def complete(
        self, model: str, messages: ChatHistory, *, think: bool | None = None
    ) -> str:
        return self.title

    async def aclose(self) -> None:
        return None


@pytest.fixture(scope="session")
def database_url() -> str:
    url = Settings().test_database_url
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    try:
        # Down then up: proves the migrations apply cleanly in both directions.
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    except (OSError, ConnectionError) as exc:
        pytest.exit(f"Test database unreachable ({exc}). Start it with `make db-up`.", 2)
    return url


@pytest.fixture
async def sessionmaker(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database_url, pooled=False)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE conversations, messages CASCADE"))
    yield create_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        default_model=None,
        system_prompt=None,
        log_json=False,
        log_level="WARNING",
        frontend_dist=Path("/nonexistent"),
    )


@pytest.fixture
async def client(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], llm: FakeLLM
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, sessionmaker=sessionmaker, llm=llm)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in body.splitlines() if line.strip()]
