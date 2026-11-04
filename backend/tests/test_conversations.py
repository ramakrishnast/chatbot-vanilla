import uuid

from httpx import AsyncClient


async def test_create_list_rename_delete(client: AsyncClient) -> None:
    created = await client.post("/api/conversations", json={})
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] == "New chat"

    listed = await client.get("/api/conversations")
    assert [c["id"] for c in listed.json()] == [conversation["id"]]

    renamed = await client.patch(
        f"/api/conversations/{conversation['id']}", json={"title": "Trip plans"}
    )
    assert renamed.json()["title"] == "Trip plans"

    detail = await client.get(f"/api/conversations/{conversation['id']}")
    assert detail.json()["messages"] == []

    deleted = await client.delete(f"/api/conversations/{conversation['id']}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/conversations/{conversation['id']}")
    assert missing.status_code == 404


async def test_unknown_conversation_is_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/conversations/{uuid.uuid4()}/messages", json={"content": "x"}
    )
    assert response.status_code == 404


async def test_empty_message_is_rejected(client: AsyncClient) -> None:
    conversation = (await client.post("/api/conversations", json={})).json()
    response = await client.post(
        f"/api/conversations/{conversation['id']}/messages", json={"content": ""}
    )
    assert response.status_code == 422


async def test_most_recently_used_conversation_is_listed_first(client: AsyncClient) -> None:
    first = (await client.post("/api/conversations", json={})).json()
    second = (await client.post("/api/conversations", json={})).json()
    await client.post(f"/api/conversations/{first['id']}/messages", json={"content": "hi"})
    listed = [c["id"] for c in (await client.get("/api/conversations")).json()]
    assert listed == [first["id"], second["id"]]
