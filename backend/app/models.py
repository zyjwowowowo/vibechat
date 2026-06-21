from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.utcnow()


def expires_tomorrow() -> datetime:
    return utcnow() + timedelta(hours=24)


class AnonymousUser(Base):
    __tablename__ = "anonymous_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(32))
    avatar_seed: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=expires_tomorrow, index=True)


class EmotionEntry(Base):
    __tablename__ = "emotion_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("anonymous_users.id", ondelete="CASCADE"), index=True)
    input_text: Mapped[str] = mapped_column(Text)
    primary_emotion: Mapped[str] = mapped_column(String(24))
    distribution: Mapped[dict] = mapped_column(JSON)
    valence: Mapped[float] = mapped_column(Float)
    arousal: Mapped[float] = mapped_column(Float)
    intensity: Mapped[float] = mapped_column(Float)
    keywords: Mapped[list] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(String(240))
    safety_level: Mapped[str] = mapped_column(String(16), default="normal")
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=expires_tomorrow, index=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(12), default="human")
    status: Mapped[str] = mapped_column(String(12), default="active")
    emotion_label: Mapped[str] = mapped_column(String(24))
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=expires_tomorrow, index=True)
    participants: Mapped[list["Participant"]] = relationship(cascade="all, delete-orphan")
    messages: Mapped[list["Message"]] = relationship(cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("anonymous_users.id", ondelete="CASCADE"), nullable=True)
    nickname: Mapped[str] = mapped_column(String(32))
    avatar_seed: Mapped[str] = mapped_column(String(24))
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)


class MatchTicket(Base):
    __tablename__ = "match_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("anonymous_users.id", ondelete="CASCADE"), index=True)
    emotion_id: Mapped[str] = mapped_column(ForeignKey("emotion_entries.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12), default="waiting", index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=expires_tomorrow, index=True)

    __table_args__ = (Index("ix_waiting_created", "status", "created_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    sender_user_id: Mapped[str | None] = mapped_column(ForeignKey("anonymous_users.id", ondelete="SET NULL"), nullable=True)
    sender_name: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(12), default="user")
    content: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, default=expires_tomorrow, index=True)

