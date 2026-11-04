import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_MESSAGE_CHARS = 100_000


class ModelInfo(BaseModel):
    name: str
    size: int | None = None
    parameter_size: str | None = None
    family: str | None = None
    capabilities: list[str] = []


class ModelList(BaseModel):
    models: list[ModelInfo]
    default: str | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    position: int
    role: str
    content: str
    thinking: str | None
    model: str | None
    status: str
    created_at: datetime


class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    model: str | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: str | None = Field(default=None, min_length=1, max_length=200)


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    model: str | None = Field(default=None, max_length=200)


class EditMessage(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    model: str | None = Field(default=None, max_length=200)


class Regenerate(BaseModel):
    model: str | None = Field(default=None, max_length=200)
