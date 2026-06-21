from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SessionResponse(BaseModel):
    token: str
    user_id: str
    nickname: str
    avatar_seed: str
    email: str | None = None
    is_guest: bool = True


class AuthRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    guest_token: str | None = None
    device_name: str = Field(default="网页端", max_length=80)

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("请输入有效邮箱")
        return value


class EmotionRequest(BaseModel):
    text: str = Field(min_length=2, max_length=800)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("再多说一点点吧")
        return value


class EmotionResult(BaseModel):
    id: str | None = None
    primary_emotion: str
    distribution: dict[str, float]
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)
    intensity: float = Field(ge=0, le=1)
    keywords: list[str] = Field(max_length=5)
    explanation: str = Field(max_length=240)
    safety_level: str = "normal"
    degraded: bool = False


class MatchRequest(BaseModel):
    emotion_id: str
    mode: Literal["similar", "complementary", "private_group"] = "similar"


class MatchResponse(BaseModel):
    ticket_id: str
    status: str
    conversation_id: str | None = None
    match_score: float | None = None
    waited_seconds: int = 0
    mode: str = "similar"


class MatchFallbackRequest(BaseModel):
    choice: Literal["continue", "direct", "ai"]


class ParticipantResponse(BaseModel):
    nickname: str
    avatar_seed: str
    is_ai: bool
    is_self: bool
    online: bool = False


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        return value.strip()


class MessageResponse(BaseModel):
    id: str
    sender_name: str
    role: str
    content: str
    sequence: int
    created_at: datetime
    is_self: bool = False


class ConversationResponse(BaseModel):
    id: str
    kind: str
    status: str
    emotion_label: str
    match_score: float | None
    participants: list[ParticipantResponse]
    messages: list[MessageResponse]
    summary: str | None = None


class AssistRequest(BaseModel):
    kind: Literal["opening", "gentle_rewrite", "icebreaker", "summary"]
    draft: str = Field(default="", max_length=1000)


class AssistResponse(BaseModel):
    kind: str
    suggestion: str


class RoomResponse(BaseModel):
    id: str
    conversation_id: str
    slug: str
    title: str
    emotion_label: str
    description: str
    member_count: int = 0
    joined: bool = False


class EmotionHistoryItem(BaseModel):
    id: str
    primary_emotion: str
    intensity: float
    valence: float
    arousal: float
    explanation: str
    created_at: datetime


class ConversationHistoryItem(BaseModel):
    id: str
    kind: str
    emotion_label: str
    status: str
    created_at: datetime
    summary: str | None = None
    peer_names: list[str] = Field(default_factory=list)
