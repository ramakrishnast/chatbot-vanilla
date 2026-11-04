"""Conversation logic shared by the routers: model choice, history, and streaming replies."""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anyio
from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.models import Conversation, Message, MessageStatus, Role
from app.ollama import ChatHistory, LLMClient, OllamaError
from app.schemas import MessageOut, ModelInfo

log = logging.getLogger(__name__)

NDJSON = "application/x-ndjson"
TITLE_TIMEOUT_SECONDS = 30.0
TITLE_MAX_WORDS = 8
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ------------------------------------------------------------------ lookups


async def load_conversation(session: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conversation = await session.scalar(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


async def touch(session: AsyncSession, conversation_id: uuid.UUID) -> None:
    """Bump updated_at so the conversation moves to the top of the sidebar."""
    await session.execute(
        update(Conversation).where(Conversation.id == conversation_id).values(updated_at=func.now())
    )


def is_chat_model(model: ModelInfo) -> bool:
    # Older Ollama versions omit capabilities; assume those models can chat.
    return not model.capabilities or "completion" in model.capabilities


async def resolve_model(llm: LLMClient, settings: Settings, *preferred: str | None) -> str:
    """First of: explicit choices (request, conversation), DEFAULT_MODEL, first installed model."""
    for candidate in preferred:
        if candidate:
            return candidate
    if settings.default_model:
        return settings.default_model
    try:
        models = await llm.list_models()
    except OllamaError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    chat_models = [m for m in models if is_chat_model(m)]
    if not chat_models:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No chat models are installed in Ollama. Run `ollama pull <model>` first.",
        )
    return chat_models[0].name


async def think_flag(llm: LLMClient, model: str) -> bool | None:
    """True for models that can think, so Ollama returns reasoning separately from the answer."""
    try:
        models = await llm.list_models()
    except OllamaError:
        return None
    for info in models:
        if info.name == model:
            return True if "thinking" in info.capabilities else None
    return None


# ------------------------------------------------------------------ history & titles


def build_history(messages: Sequence[Message], system_prompt: str | None) -> ChatHistory:
    history: ChatHistory = []
    if system_prompt:
        history.append({"role": "system", "content": system_prompt})
    for message in messages:
        if message.role == Role.ASSISTANT and not message.content.strip():
            continue  # a reply that failed or was stopped before any text arrived
        history.append({"role": message.role, "content": message.content})
    return history


def fallback_title(text: str, limit: int = 60) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed or "New chat"
    return collapsed[: limit - 1].rstrip() + "…"


def clean_title(raw: str) -> str | None:
    text = _THINK_BLOCK.sub("", raw).strip()
    if not text:
        return None
    junk = "\"'*#` "
    line = text.splitlines()[0].strip().strip(junk)
    line = re.sub(r"^title\s*:\s*", "", line, flags=re.IGNORECASE)
    line = line.strip().strip(junk).rstrip(".")
    if not line:
        return None
    # Small models often ignore the length instruction.
    words = line.split()
    if len(words) > TITLE_MAX_WORDS:
        line = " ".join(words[:TITLE_MAX_WORDS])
    return line[:80]


async def generate_title(
    llm: LLMClient, model: str, think: bool | None, user_text: str, reply: str
) -> str | None:
    prompt: ChatHistory = [
        {
            "role": "system",
            "content": "You name chat conversations. Reply with a 3-6 word title only: "
            "no quotes, no punctuation at the end, no explanation.",
        },
        {
            "role": "user",
            "content": f"User: {user_text[:2000]}\n\nAssistant: {reply[:2000]}\n\nTitle:",
        },
    ]
    try:
        raw = await asyncio.wait_for(
            llm.complete(model, prompt, think=False if think else None),
            timeout=TITLE_TIMEOUT_SECONDS,
        )
    except (OllamaError, TimeoutError) as exc:
        log.info("title generation skipped", extra={"reason": str(exc) or type(exc).__name__})
        return None
    return clean_title(raw)


# ------------------------------------------------------------------ streaming


def ndjson(event: dict[str, Any]) -> bytes:
    return (json.dumps(event, default=str) + "\n").encode()


def message_event(kind: str, message: Message) -> dict[str, Any]:
    return {"type": kind, "message": MessageOut.model_validate(message).model_dump(mode="json")}


async def _save_reply(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    *,
    model: str,
    content: str,
    thinking: str,
    message_status: MessageStatus,
) -> Message | None:
    async with sessionmaker() as session:
        last = await session.scalar(
            select(func.max(Message.position)).where(Message.conversation_id == conversation_id)
        )
        message = Message(
            conversation_id=conversation_id,
            position=(last if last is not None else -1) + 1,
            role=Role.ASSISTANT,
            content=content,
            thinking=thinking or None,
            model=model,
            status=message_status,
        )
        session.add(message)
        await touch(session, conversation_id)
        try:
            await session.commit()
        except IntegrityError:
            # The conversation was deleted (or edited) while this reply was streaming.
            log.warning("reply discarded", extra={"conversation_id": str(conversation_id)})
            return None
        await session.refresh(message)
        return message


async def _save_title(
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    *,
    title: str,
    replaces: str,
) -> bool:
    async with sessionmaker() as session:
        # Only replace the placeholder; never overwrite a title the user set meanwhile.
        result = await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.title == replaces)
            .values(title=title)
        )
        await session.commit()
        return bool(getattr(result, "rowcount", 0))


def stream_reply(
    *,
    llm: LLMClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    model: str,
    think: bool | None,
    history: ChatHistory,
    prelude: Sequence[dict[str, Any]] = (),
    title_from: tuple[str, str] | None = None,
) -> StreamingResponse:
    """Stream an assistant reply as NDJSON events and persist it when it ends.

    Events: user_message, thinking, delta, error, title, done. If the client disconnects
    (the stop button aborts the request), whatever streamed so far is saved as "stopped".
    `title_from` is (user_text, placeholder_title) when this is the first exchange.
    """

    async def events() -> AsyncIterator[bytes]:
        for event in prelude:
            yield ndjson(event)
        content: list[str] = []
        thinking: list[str] = []
        outcome = MessageStatus.COMPLETE
        error: str | None = None
        try:
            try:
                async for chunk in llm.stream_chat(model, history, think=think):
                    if chunk.thinking:
                        thinking.append(chunk.thinking)
                        yield ndjson({"type": "thinking", "content": chunk.thinking})
                    if chunk.content:
                        content.append(chunk.content)
                        yield ndjson({"type": "delta", "content": chunk.content})
            except OllamaError as exc:
                outcome, error = MessageStatus.ERROR, str(exc)
                log.warning("ollama stream failed", extra={"model": model, "error": error})
        except BaseException:
            # Client went away mid-stream: keep the partial reply, then let cancellation proceed.
            with anyio.CancelScope(shield=True):
                await _save_reply(
                    sessionmaker,
                    conversation_id,
                    model=model,
                    content="".join(content),
                    thinking="".join(thinking),
                    message_status=MessageStatus.STOPPED,
                )
            raise

        reply = "".join(content)
        message = await _save_reply(
            sessionmaker,
            conversation_id,
            model=model,
            content=reply,
            thinking="".join(thinking),
            message_status=outcome,
        )
        if error is not None:
            yield ndjson({"type": "error", "detail": error})
        if title_from and outcome == MessageStatus.COMPLETE and message is not None:
            user_text, placeholder = title_from
            title = await generate_title(llm, model, think, user_text, reply)
            if title and await _save_title(
                sessionmaker, conversation_id, title=title, replaces=placeholder
            ):
                yield ndjson({"type": "title", "title": title})
        if message is not None:
            yield ndjson(message_event("done", message))
        else:
            yield ndjson({"type": "done", "message": None})

    return StreamingResponse(
        events(),
        media_type=NDJSON,
        # Disable proxy buffering so tokens reach the browser as they are generated.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
