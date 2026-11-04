from typing import Any

from httpx import AsyncClient

from app.chat_service import clean_title, fallback_title
from app.ollama import ChatChunk
from tests.conftest import FakeLLM, events


async def new_chat(client: AsyncClient, **body: Any) -> str:
    response = await client.post("/api/conversations", json=body)
    return str(response.json()["id"])


async def send(client: AsyncClient, cid: str, content: str, **extra: Any) -> list[dict[str, Any]]:
    response = await client.post(
        f"/api/conversations/{cid}/messages", json={"content": content, **extra}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return events(response.text)


async def test_first_message_streams_reply_and_names_the_chat(
    client: AsyncClient, llm: FakeLLM
) -> None:
    cid = await new_chat(client)
    stream = await send(client, cid, "Say hello")

    assert [e["type"] for e in stream] == ["user_message", "delta", "delta", "title", "done"]
    assert stream[0]["message"]["content"] == "Say hello"
    assert "".join(e["content"] for e in stream if e["type"] == "delta") == "Hello there"
    assert stream[3]["title"] == "Friendly Greeting"
    done = stream[-1]["message"]
    assert done["role"] == "assistant"
    assert done["content"] == "Hello there"
    assert done["status"] == "complete"
    assert done["model"] == "fake-chat:1b"

    detail = (await client.get(f"/api/conversations/{cid}")).json()
    assert detail["title"] == "Friendly Greeting"
    assert detail["model"] == "fake-chat:1b"
    assert [(m["role"], m["content"]) for m in detail["messages"]] == [
        ("user", "Say hello"),
        ("assistant", "Hello there"),
    ]
    assert llm.calls[0]["messages"] == [{"role": "user", "content": "Say hello"}]


async def test_follow_up_sends_full_history_and_keeps_title(
    client: AsyncClient, llm: FakeLLM
) -> None:
    cid = await new_chat(client)
    await send(client, cid, "Say hello")
    stream = await send(client, cid, "Again")

    assert "title" not in [e["type"] for e in stream]
    assert [m["content"] for m in llm.calls[-1]["messages"]] == [
        "Say hello",
        "Hello there",
        "Again",
    ]


async def test_chosen_model_is_used_and_remembered(client: AsyncClient, llm: FakeLLM) -> None:
    cid = await new_chat(client)
    await send(client, cid, "hi", model="fake-thinker:4b")
    assert llm.calls[-1]["model"] == "fake-thinker:4b"
    assert llm.calls[-1]["think"] is True  # thinking-capable model

    await send(client, cid, "again")
    assert llm.calls[-1]["model"] == "fake-thinker:4b"


async def test_thinking_is_streamed_and_stored(client: AsyncClient, llm: FakeLLM) -> None:
    llm.chunks = [ChatChunk(thinking="Let me think."), ChatChunk(content="42")]
    cid = await new_chat(client)
    stream = await send(client, cid, "Meaning of life?")

    assert {"type": "thinking", "content": "Let me think."} in stream
    assert stream[-1]["message"]["thinking"] == "Let me think."
    assert stream[-1]["message"]["content"] == "42"


async def test_ollama_failure_keeps_partial_reply(client: AsyncClient, llm: FakeLLM) -> None:
    llm.fail_after_chunks = "model ran out of memory"
    cid = await new_chat(client)
    stream = await send(client, cid, "hi")

    error = next(e for e in stream if e["type"] == "error")
    assert error["detail"] == "model ran out of memory"
    assert stream[-1]["message"]["status"] == "error"
    assert stream[-1]["message"]["content"] == "Hello there"
    assert "title" not in [e["type"] for e in stream]


async def test_regenerate_replaces_last_reply(client: AsyncClient, llm: FakeLLM) -> None:
    cid = await new_chat(client)
    await send(client, cid, "Tell me a joke")
    llm.chunks = [ChatChunk(content="A better joke")]

    response = await client.post(f"/api/conversations/{cid}/regenerate", json={})
    assert response.status_code == 200
    assert events(response.text)[-1]["message"]["content"] == "A better joke"
    assert llm.calls[-1]["messages"] == [{"role": "user", "content": "Tell me a joke"}]

    messages = (await client.get(f"/api/conversations/{cid}")).json()["messages"]
    assert [m["content"] for m in messages] == ["Tell me a joke", "A better joke"]


async def test_regenerate_without_messages_is_rejected(client: AsyncClient) -> None:
    cid = await new_chat(client)
    response = await client.post(f"/api/conversations/{cid}/regenerate", json={})
    assert response.status_code == 400


async def test_edit_rewrites_message_and_drops_later_turns(
    client: AsyncClient, llm: FakeLLM
) -> None:
    cid = await new_chat(client)
    first = await send(client, cid, "What is 2+2?")
    await send(client, cid, "And 3+3?")
    first_id = first[0]["message"]["id"]
    llm.chunks = [ChatChunk(content="6")]

    response = await client.put(
        f"/api/conversations/{cid}/messages/{first_id}", json={"content": "What is 3+3?"}
    )
    stream = events(response.text)
    assert stream[0]["type"] == "user_message"
    assert stream[0]["message"]["content"] == "What is 3+3?"
    assert llm.calls[-1]["messages"] == [{"role": "user", "content": "What is 3+3?"}]

    messages = (await client.get(f"/api/conversations/{cid}")).json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "What is 3+3?"),
        ("assistant", "6"),
    ]


async def test_assistant_messages_cannot_be_edited(client: AsyncClient) -> None:
    cid = await new_chat(client)
    stream = await send(client, cid, "hi")
    reply_id = stream[-1]["message"]["id"]
    response = await client.put(
        f"/api/conversations/{cid}/messages/{reply_id}", json={"content": "nope"}
    )
    assert response.status_code == 400


async def test_system_prompt_is_prepended(client: AsyncClient, llm: FakeLLM, settings) -> None:
    settings.system_prompt = "Be brief."
    cid = await new_chat(client)
    await send(client, cid, "hi")
    assert llm.calls[-1]["messages"][0] == {"role": "system", "content": "Be brief."}


def test_title_helpers() -> None:
    assert clean_title('<think>hmm</think>\n"Title: Rust Lifetimes Explained."') == (
        "Rust Lifetimes Explained"
    )
    assert clean_title("<think>only thoughts</think>") is None
    assert clean_title("one two three four five six seven eight nine ten") == (
        "one two three four five six seven eight"
    )
    assert fallback_title("short question") == "short question"
    long = fallback_title("word " * 40)
    assert len(long) == 60
    assert long.endswith("…")
