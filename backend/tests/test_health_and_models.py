from httpx import AsyncClient

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
