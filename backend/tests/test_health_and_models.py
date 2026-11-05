from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db import create_engine, create_sessionmaker
from app.main import create_app
from tests.conftest import FakeLLM


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


async def test_ready_when_everything_is_up(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": True, "ollama": True}


async def test_ready_reports_ollama_down(client: AsyncClient, llm: FakeLLM) -> None:
    llm.healthy = False
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": True, "ollama": False}


async def test_models_hide_embedding_only_models(client: AsyncClient) -> None:
    response = await client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert [m["name"] for m in body["models"]] == ["fake-chat:1b", "fake-thinker:4b"]
    assert body["default"] == "fake-chat:1b"


async def test_database_down_is_a_clear_503(llm: FakeLLM) -> None:
    # Nothing listens on port 1, so every connection attempt is refused.
    url = "postgresql+asyncpg://chat:chat@127.0.0.1:1/chat"
    engine = create_engine(url, pooled=False)
    app = create_app(
        Settings(database_url=url, log_json=False, frontend_dist=Path("/nonexistent")),
        sessionmaker=create_sessionmaker(engine),
        llm=llm,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/conversations")
        ready = await http.get("/ready")
    await engine.dispose()

    assert response.status_code == 503
    assert "make db-up" in response.json()["detail"]
    assert ready.status_code == 503
    assert ready.json()["checks"]["database"] is False
