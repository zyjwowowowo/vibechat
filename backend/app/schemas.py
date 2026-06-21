from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SessionResponse(BaseModel):
    token: str
    user_id: str
    nickname: str
    avatar_seed: str


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


class MatchResponse(BaseModel):
    ticket_id: str
    status: str
    conversation_id: str | None = None
    match_score: float | None = None
    waited_seconds: int = 0


class ParticipantResponse(BaseModel):
    nickname: str
    avatar_seed: str
    is_ai: bool
    is_self: bool


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

