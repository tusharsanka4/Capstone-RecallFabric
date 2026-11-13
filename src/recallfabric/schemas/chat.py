from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from recallfabric.schemas.memory import MemoryRanked, MemoryRead, NonemptyText


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: Annotated[NonemptyText, Field(max_length=255)]
    message: NonemptyText
    history: list[ChatMessage] | None = None
    conversation_id: str | None = Field(default=None, max_length=255)
    extract: bool = False


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reply: str
    memories_used: list[MemoryRanked] = Field(default_factory=list)
    model: str
    extracted: list[MemoryRead] = Field(default_factory=list)
    extracted_memories: list[MemoryRead] = Field(default_factory=list)
