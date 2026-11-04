import uuid

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.chat_service import (
    build_history,
    fallback_title,
    load_conversation,
    message_event,
    resolve_model,
    stream_reply,
    think_flag,
    touch,
)
from app.deps import LLMDep, SessionDep, SessionmakerDep, SettingsDep
from app.models import DEFAULT_TITLE, Conversation, Message, Role
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationSummary,
    ConversationUpdate,
    EditMessage,
    Regenerate,
    SendMessage,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

LIST_LIMIT = 500


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(session: SessionDep) -> list[Conversation]:
    result = await session.scalars(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(LIST_LIMIT)
    )
    return list(result)


@router.post("", response_model=ConversationSummary, status_code=status.HTTP_201_CREATED)
async def create_conversation(body: ConversationCreate, session: SessionDep) -> Conversation:
    conversation = Conversation(title=body.title or DEFAULT_TITLE, model=body.model)
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> Conversation:
    return await load_conversation(session, conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def update_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, session: SessionDep
) -> Conversation:
    conversation = await load_conversation(session, conversation_id)
    if body.title is not None:
        conversation.title = body.title.strip() or conversation.title
    if body.model is not None:
        conversation.model = body.model
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, session: SessionDep) -> Response:
    conversation = await load_conversation(session, conversation_id)
    await session.delete(conversation)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: SendMessage,
    session: SessionDep,
    sessionmaker: SessionmakerDep,
    llm: LLMDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Add a user message and stream the assistant's reply."""
    conversation = await load_conversation(session, conversation_id)
    model = await resolve_model(llm, settings, body.model, conversation.model)
    previous = list(conversation.messages)
    first_exchange = not previous and conversation.title == DEFAULT_TITLE

    user_message = Message(
        conversation_id=conversation.id,
        position=previous[-1].position + 1 if previous else 0,
        role=Role.USER,
        content=body.content,
    )
    session.add(user_message)
    conversation.model = model
    placeholder = fallback_title(body.content)
    if first_exchange:
        conversation.title = placeholder
    await touch(session, conversation.id)
    await session.commit()
    await session.refresh(user_message)

    return stream_reply(
        llm=llm,
        sessionmaker=sessionmaker,
        conversation_id=conversation.id,
        model=model,
        think=await think_flag(llm, model),
        history=build_history([*previous, user_message], settings.system_prompt),
        prelude=[message_event("user_message", user_message)],
        title_from=(body.content, placeholder) if first_exchange else None,
    )


@router.post("/{conversation_id}/regenerate")
async def regenerate(
    conversation_id: uuid.UUID,
    body: Regenerate,
    session: SessionDep,
    sessionmaker: SessionmakerDep,
    llm: LLMDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Replace the last assistant reply with a new one (optionally from another model)."""
    conversation = await load_conversation(session, conversation_id)
    remaining = list(conversation.messages)
    while remaining and remaining[-1].role == Role.ASSISTANT:
        await session.delete(remaining.pop())
    if not remaining:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no message to reply to")

    model = await resolve_model(llm, settings, body.model, conversation.model)
    conversation.model = model
    await session.commit()

    return stream_reply(
        llm=llm,
        sessionmaker=sessionmaker,
        conversation_id=conversation.id,
        model=model,
        think=await think_flag(llm, model),
        history=build_history(remaining, settings.system_prompt),
    )


@router.put("/{conversation_id}/messages/{message_id}")
async def edit_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    body: EditMessage,
    session: SessionDep,
    sessionmaker: SessionmakerDep,
    llm: LLMDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Change an earlier user message, drop everything after it, and stream a new reply."""
    conversation = await load_conversation(session, conversation_id)
    target = next((m for m in conversation.messages if m.id == message_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if target.role != Role.USER:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only your own messages can be edited")

    kept = [m for m in conversation.messages if m.position <= target.position]
    for message in conversation.messages:
        if message.position > target.position:
            await session.delete(message)
    target.content = body.content
    model = await resolve_model(llm, settings, body.model, conversation.model)
    conversation.model = model
    await touch(session, conversation.id)
    await session.commit()
    await session.refresh(target)

    return stream_reply(
        llm=llm,
        sessionmaker=sessionmaker,
        conversation_id=conversation.id,
        model=model,
        think=await think_flag(llm, model),
        history=build_history(kept, settings.system_prompt),
        prelude=[message_event("user_message", target)],
    )
