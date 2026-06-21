import asyncio
import random
from contextlib import suppress
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .auth import get_current_user, new_token
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .llm import LLMService
from .matching import create_ai_conversation, enqueue_and_match
from .models import (
    AnonymousUser,
    Conversation,
    EmotionEntry,
    MatchTicket,
    Message,
    Participant,
)
from .realtime import manager
from .schemas import (
    ConversationResponse,
    EmotionRequest,
    EmotionResult,
    MatchRequest,
    MatchResponse,
    MessageRequest,
    MessageResponse,
    ParticipantResponse,
    SessionResponse,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADJECTIVES = ["雾蓝", "晚风", "月光", "松软", "微光", "晴空", "星河", "琥珀"]
ANIMALS = ["水獭", "鲸鱼", "海豹", "小鹿", "狐狸", "云雀", "猫咪", "兔子"]


@app.on_event("startup")
async def startup() -> None:
    Base.metadata.create_all(bind=engine)
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    task = getattr(app.state, "cleanup_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        with SessionLocal() as db:
            now = datetime.utcnow()
            for model in (Message, MatchTicket, EmotionEntry, Conversation, AnonymousUser):
                db.execute(delete(model).where(model.expires_at < now))
            db.commit()


def require_emotion(db: Session, emotion_id: str, user_id: str) -> EmotionEntry:
    emotion = db.scalar(
        select(EmotionEntry).where(EmotionEntry.id == emotion_id, EmotionEntry.user_id == user_id)
    )
    if not emotion:
        raise HTTPException(404, "找不到这次情绪分析")
    return emotion


def require_participant(db: Session, conversation_id: str, user_id: str) -> Participant:
    participant = db.scalar(
        select(Participant).where(
            Participant.conversation_id == conversation_id, Participant.user_id == user_id
        )
    )
    if not participant:
        raise HTTPException(403, "你不在这段会话中")
    return participant


def serialize_message(message: Message, user_id: str) -> dict:
    return {
        "id": message.id,
        "sender_name": message.sender_name,
        "role": message.role,
        "content": message.content,
        "sequence": message.sequence,
        "created_at": message.created_at.isoformat() + "Z",
        "is_self": message.sender_user_id == user_id,
    }


def add_message(db: Session, conversation: Conversation, user: AnonymousUser, content: str) -> Message:
    sequence = (db.scalar(select(func.max(Message.sequence)).where(Message.conversation_id == conversation.id)) or 0) + 1
    message = Message(
        conversation_id=conversation.id,
        sender_user_id=user.id,
        sender_name=user.nickname,
        role="user",
        content=content,
        sequence=sequence,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


async def generate_ai_reply(conversation_id: str) -> None:
    await asyncio.sleep(0.7)
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        if not conversation or conversation.kind != "ai":
            return
        messages = db.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence.asc())
        ).all()
        history = [{"role": item.role, "content": item.content} for item in messages]
        content = await LLMService().companion_reply(conversation.emotion_label, history)
        sequence = (messages[-1].sequence if messages else 0) + 1
        reply = Message(
            conversation_id=conversation_id,
            sender_user_id=None,
            sender_name="月光水獭 · AI",
            role="ai",
            content=content,
            sequence=sequence,
        )
        db.add(reply)
        db.commit()
        db.refresh(reply)
        payload = {
            "type": "message.created",
            "message": serialize_message(reply, ""),
        }
    await manager.broadcast(conversation_id, payload)


@app.get("/health")
def health() -> dict:
    service = LLMService()
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "model": settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model,
        "llm_configured": service.configured,
    }


@app.post("/api/v1/sessions", response_model=SessionResponse)
def create_session(db: Session = Depends(get_db)) -> SessionResponse:
    nickname = f"{random.choice(ADJECTIVES)}{random.choice(ANIMALS)}"
    user = AnonymousUser(token=new_token(), nickname=nickname, avatar_seed=f"seed-{random.randint(1, 12)}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return SessionResponse(token=user.token, user_id=user.id, nickname=user.nickname, avatar_seed=user.avatar_seed)


@app.get("/api/v1/sessions/me", response_model=SessionResponse)
def current_session(user: AnonymousUser = Depends(get_current_user)) -> SessionResponse:
    return SessionResponse(token=user.token, user_id=user.id, nickname=user.nickname, avatar_seed=user.avatar_seed)


@app.post("/api/v1/emotions/analyze", response_model=EmotionResult)
async def analyze_emotion(
    request: EmotionRequest,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> EmotionResult:
    result = await LLMService().analyze(request.text)
    entry = EmotionEntry(
        user_id=user.id,
        input_text=request.text,
        primary_emotion=result.primary_emotion,
        distribution=result.distribution,
        valence=result.valence,
        arousal=result.arousal,
        intensity=result.intensity,
        keywords=result.keywords,
        explanation=result.explanation,
        safety_level=result.safety_level,
        degraded=result.degraded,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    result.id = entry.id
    return result


@app.post("/api/v1/matches", response_model=MatchResponse)
def create_match(
    request: MatchRequest,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> MatchResponse:
    emotion = require_emotion(db, request.emotion_id, user.id)
    ticket = enqueue_and_match(db, user, emotion)
    return MatchResponse(
        ticket_id=ticket.id,
        status=ticket.status,
        conversation_id=ticket.conversation_id,
        match_score=ticket.match_score,
    )


@app.get("/api/v1/matches/{ticket_id}", response_model=MatchResponse)
def get_match(
    ticket_id: str,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> MatchResponse:
    ticket = db.scalar(select(MatchTicket).where(MatchTicket.id == ticket_id, MatchTicket.user_id == user.id))
    if not ticket:
        raise HTTPException(404, "匹配请求不存在")
    waited = max(0, int((datetime.utcnow() - ticket.created_at).total_seconds()))
    if ticket.status == "waiting" and waited >= settings.match_timeout_seconds:
        emotion = require_emotion(db, ticket.emotion_id, user.id)
        create_ai_conversation(db, ticket, user, emotion)
        db.commit()
        db.refresh(ticket)
    return MatchResponse(
        ticket_id=ticket.id,
        status=ticket.status,
        conversation_id=ticket.conversation_id,
        match_score=ticket.match_score,
        waited_seconds=waited,
    )


@app.delete("/api/v1/matches/{ticket_id}")
def cancel_match(
    ticket_id: str,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> dict:
    ticket = db.scalar(select(MatchTicket).where(MatchTicket.id == ticket_id, MatchTicket.user_id == user.id))
    if ticket and ticket.status == "waiting":
        ticket.status = "cancelled"
        db.commit()
    return {"status": "cancelled"}


@app.get("/api/v1/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> ConversationResponse:
    require_participant(db, conversation_id, user.id)
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "会话不存在")
    participants = db.scalars(select(Participant).where(Participant.conversation_id == conversation_id)).all()
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.sequence.asc())
    ).all()
    return ConversationResponse(
        id=conversation.id,
        kind=conversation.kind,
        status=conversation.status,
        emotion_label=conversation.emotion_label,
        match_score=conversation.match_score,
        participants=[
            ParticipantResponse(
                nickname=item.nickname,
                avatar_seed=item.avatar_seed,
                is_ai=item.is_ai,
                is_self=item.user_id == user.id,
            )
            for item in participants
        ],
        messages=[MessageResponse(**serialize_message(item, user.id)) for item in messages],
    )


@app.post("/api/v1/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def post_message(
    conversation_id: str,
    request: MessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> MessageResponse:
    require_participant(db, conversation_id, user.id)
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.status != "active":
        raise HTTPException(409, "会话已经结束")
    message = add_message(db, conversation, user, request.content)
    payload = {"type": "message.created", "message": serialize_message(message, user.id)}
    await manager.broadcast(conversation_id, payload)
    if conversation.kind == "ai":
        background_tasks.add_task(generate_ai_reply, conversation_id)
    return MessageResponse(**serialize_message(message, user.id))


@app.websocket("/api/v1/ws/conversations/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: str) -> None:
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    token_protocol = next((item for item in protocols if item.startswith("token.")), "")
    token = token_protocol.removeprefix("token.")
    with SessionLocal() as db:
        user = db.scalar(select(AnonymousUser).where(AnonymousUser.token == token))
        participant = (
            db.scalar(
                select(Participant).where(
                    Participant.conversation_id == conversation_id,
                    Participant.user_id == user.id,
                )
            )
            if user
            else None
        )
        if not user or not participant:
            await websocket.close(code=4401)
            return
        user_id, nickname = user.id, user.nickname
    await manager.connect(conversation_id, websocket, subprotocol="vibechat")
    await manager.broadcast(conversation_id, {"type": "presence", "nickname": nickname, "online": True}, websocket)
    try:
        while True:
            event = await websocket.receive_json()
            if event.get("type") == "typing":
                await manager.broadcast(
                    conversation_id,
                    {"type": "typing", "nickname": nickname, "active": bool(event.get("active"))},
                    websocket,
                )
                continue
            if event.get("type") != "message" or not str(event.get("content", "")).strip():
                continue
            content = str(event["content"]).strip()[:1000]
            with SessionLocal() as db:
                conversation = db.get(Conversation, conversation_id)
                current_user = db.get(AnonymousUser, user_id)
                if not conversation or not current_user:
                    continue
                message = add_message(db, conversation, current_user, content)
                payload = {"type": "message.created", "message": serialize_message(message, user_id)}
                kind = conversation.kind
            await manager.broadcast(conversation_id, payload)
            if kind == "ai":
                asyncio.create_task(generate_ai_reply(conversation_id))
    except WebSocketDisconnect:
        manager.disconnect(conversation_id, websocket)
        await manager.broadcast(conversation_id, {"type": "presence", "nickname": nickname, "online": False})
