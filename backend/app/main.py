import asyncio
import random
from contextlib import suppress
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, inspect, select, text as sql_text
from sqlalchemy.orm import Session

from .auth import get_current_user, hash_password, new_token, verify_password
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .llm import LLMService
from .matching import create_ai_conversation, enqueue_and_match
from .models import (
    AnonymousUser,
    Account,
    Conversation,
    ConversationSummary,
    DeviceSession,
    EmotionEntry,
    MatchTicket,
    Message,
    Participant,
    PublicRoom,
    expires_persistently,
)
from .realtime import manager
from .schemas import (
    ConversationResponse,
    ConversationHistoryItem,
    AuthRequest,
    AssistRequest,
    AssistResponse,
    EmotionHistoryItem,
    EmotionRequest,
    EmotionResult,
    MatchRequest,
    MatchResponse,
    MatchFallbackRequest,
    MessageRequest,
    MessageResponse,
    ParticipantResponse,
    RoomResponse,
    SessionResponse,
)

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    # Railway preview/production domains are ephemeral. Allow only Railway's
    # HTTPS domain suffix in addition to explicitly configured origins.
    allow_origin_regex=r"https://[a-z0-9-]+\.up\.railway\.app",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADJECTIVES = ["雾蓝", "晚风", "月光", "松软", "微光", "晴空", "星河", "琥珀"]
ANIMALS = ["水獭", "鲸鱼", "海豹", "小鹿", "狐狸", "云雀", "猫咪", "兔子"]


@app.on_event("startup")
async def startup() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_legacy_columns()
    seed_public_rooms()
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())


def migrate_legacy_columns() -> None:
    """Small compatibility bridge; Alembic owns deployed schema changes going forward."""
    wanted = {
        "anonymous_users": {"account_id": "VARCHAR(36)"},
        "match_tickets": {"mode": "VARCHAR(24) DEFAULT 'similar'"},
        "participants": {"joined_at": "DATETIME", "hidden_at": "DATETIME"},
    }
    with engine.begin() as connection:
        for table_name, columns in wanted.items():
            existing = {item["name"] for item in inspect(connection).get_columns(table_name)}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(sql_text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))


def seed_public_rooms() -> None:
    room_specs = [
        ("quiet-tide", "平静潮汐", "平静", "适合慢一点说话，也适合只是待一会儿。"),
        ("soft-anxiety", "焦虑缓冲区", "焦虑", "把杂乱的担心放下来一点，彼此不催促。"),
        ("lonely-signal", "孤独信号站", "孤独", "发出一个微弱信号，也许会有人回应。"),
        ("bright-moment", "微光发生地", "喜悦", "分享今天值得被看见的一点好消息。"),
    ]
    with SessionLocal() as db:
        for slug, title, emotion, description in room_specs:
            if db.scalar(select(PublicRoom).where(PublicRoom.slug == slug)):
                continue
            conversation = Conversation(
                kind="public_room", status="active", emotion_label=emotion,
                expires_at=expires_persistently(),
            )
            db.add(conversation)
            db.flush()
            db.add(PublicRoom(
                conversation_id=conversation.id, slug=slug, title=title,
                emotion_label=emotion, description=description,
            ))
        db.commit()


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
            Participant.conversation_id == conversation_id, Participant.user_id == user_id,
            Participant.hidden_at.is_(None),
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
        **({"expires_at": expires_persistently()} if user.account_id else {}),
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
def current_session(x_session_token: str = Header(default=""), user: AnonymousUser = Depends(get_current_user), db: Session = Depends(get_db)) -> SessionResponse:
    account = db.get(Account, user.account_id) if user.account_id else None
    device = db.scalar(select(DeviceSession).where(DeviceSession.user_id == user.id, DeviceSession.revoked_at.is_(None)).order_by(DeviceSession.created_at.desc()))
    return SessionResponse(
        token=x_session_token or (device.token if device else user.token),
        user_id=user.id,
        nickname=user.nickname,
        avatar_seed=user.avatar_seed,
        email=account.email if account else None,
        is_guest=account is None,
    )


def auth_response(db: Session, user: AnonymousUser, account: Account, device_name: str) -> SessionResponse:
    device = DeviceSession(
        account_id=account.id, user_id=user.id, token=new_token(), device_name=device_name,
    )
    db.add(device)
    db.commit()
    return SessionResponse(
        token=device.token, user_id=user.id, nickname=user.nickname,
        avatar_seed=user.avatar_seed, email=account.email, is_guest=False,
    )


@app.post("/api/v1/auth/register", response_model=SessionResponse)
def register(request: AuthRequest, db: Session = Depends(get_db)) -> SessionResponse:
    if db.scalar(select(Account).where(Account.email == request.email)):
        raise HTTPException(409, "这个邮箱已经注册")
    user = db.scalar(select(AnonymousUser).where(AnonymousUser.token == request.guest_token)) if request.guest_token else None
    if user and user.account_id:
        raise HTTPException(409, "当前身份已经绑定账户")
    if not user:
        user = AnonymousUser(token=new_token(), nickname=f"{random.choice(ADJECTIVES)}{random.choice(ANIMALS)}", avatar_seed=f"seed-{random.randint(1, 12)}")
        db.add(user)
        db.flush()
    account = Account(email=request.email, password_hash=hash_password(request.password))
    db.add(account)
    db.flush()
    user.account_id = account.id
    user.expires_at = expires_persistently()
    for entry in db.scalars(select(EmotionEntry).where(EmotionEntry.user_id == user.id)):
        entry.expires_at = expires_persistently()
    db.commit()
    return auth_response(db, user, account, request.device_name)


@app.post("/api/v1/auth/login", response_model=SessionResponse)
def login(request: AuthRequest, db: Session = Depends(get_db)) -> SessionResponse:
    account = db.scalar(select(Account).where(Account.email == request.email))
    if not account or not verify_password(account.password_hash, request.password):
        raise HTTPException(401, "邮箱或密码不正确")
    user = db.scalar(select(AnonymousUser).where(AnonymousUser.account_id == account.id))
    if not user:
        raise HTTPException(404, "账户资料不存在")
    return auth_response(db, user, account, request.device_name)


@app.post("/api/v1/auth/logout")
def logout(x_session_token: str = Header(default=""), db: Session = Depends(get_db)) -> dict:
    device = db.scalar(select(DeviceSession).where(DeviceSession.token == x_session_token, DeviceSession.revoked_at.is_(None)))
    if device:
        device.revoked_at = datetime.utcnow()
        db.commit()
    return {"status": "signed_out"}


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
        **({"expires_at": expires_persistently()} if user.account_id else {}),
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
    if not user.account_id:
        raise HTTPException(403, "注册或登录后即可遇见真人")
    emotion = require_emotion(db, request.emotion_id, user.id)
    if emotion.safety_level == "crisis":
        raise HTTPException(409, "此刻先不要进入陌生人匹配，请优先联系可信任的人或当地紧急支持")
    ticket = enqueue_and_match(db, user, emotion, request.mode)
    return MatchResponse(
        ticket_id=ticket.id,
        status=ticket.status,
        conversation_id=ticket.conversation_id,
        match_score=ticket.match_score,
        mode=ticket.mode,
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
        if ticket.mode == "private_group":
            ticket.status = "needs_choice"
            db.commit()
        else:
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
        mode=ticket.mode,
    )


@app.post("/api/v1/matches/{ticket_id}/fallback", response_model=MatchResponse)
def choose_match_fallback(
    ticket_id: str,
    request: MatchFallbackRequest,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> MatchResponse:
    ticket = db.scalar(select(MatchTicket).where(MatchTicket.id == ticket_id, MatchTicket.user_id == user.id))
    if not ticket or ticket.status not in {"waiting", "needs_choice"}:
        raise HTTPException(409, "这次匹配已经结束")
    emotion = require_emotion(db, ticket.emotion_id, user.id)
    if request.choice == "continue":
        ticket.status = "waiting"
        ticket.created_at = datetime.utcnow()
        db.commit()
    elif request.choice == "ai":
        create_ai_conversation(db, ticket, user, emotion)
        db.commit()
    else:
        ticket.status = "cancelled"
        db.commit()
        ticket = enqueue_and_match(db, user, emotion, "similar")
    db.refresh(ticket)
    return MatchResponse(
        ticket_id=ticket.id, status=ticket.status, conversation_id=ticket.conversation_id,
        match_score=ticket.match_score, mode=ticket.mode,
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
    summary = db.scalar(select(ConversationSummary).where(
        ConversationSummary.conversation_id == conversation_id,
        ConversationSummary.user_id == user.id,
    ))
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
        summary=summary.content if summary else None,
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


@app.get("/api/v1/rooms", response_model=list[RoomResponse])
def list_rooms(db: Session = Depends(get_db), user: AnonymousUser = Depends(get_current_user)) -> list[RoomResponse]:
    rooms = db.scalars(select(PublicRoom).order_by(PublicRoom.created_at.asc())).all()
    result: list[RoomResponse] = []
    for room in rooms:
        members = db.scalar(select(func.count(Participant.id)).where(Participant.conversation_id == room.conversation_id)) or 0
        joined = bool(db.scalar(select(Participant.id).where(
            Participant.conversation_id == room.conversation_id,
            Participant.user_id == user.id,
            Participant.hidden_at.is_(None),
        )))
        result.append(RoomResponse(**{
            "id": room.id, "conversation_id": room.conversation_id, "slug": room.slug,
            "title": room.title, "emotion_label": room.emotion_label,
            "description": room.description, "member_count": members, "joined": joined,
        }))
    return result


@app.post("/api/v1/rooms/{room_id}/join", response_model=ConversationResponse)
def join_room(room_id: str, db: Session = Depends(get_db), user: AnonymousUser = Depends(get_current_user)) -> ConversationResponse:
    if not user.account_id:
        raise HTTPException(403, "登录后即可加入公开房间")
    room = db.get(PublicRoom, room_id)
    if not room:
        raise HTTPException(404, "房间不存在")
    participant = db.scalar(select(Participant).where(
        Participant.conversation_id == room.conversation_id, Participant.user_id == user.id,
    ))
    if participant:
        participant.hidden_at = None
    else:
        db.add(Participant(
            conversation_id=room.conversation_id, user_id=user.id,
            nickname=user.nickname, avatar_seed=user.avatar_seed,
        ))
    db.commit()
    return get_conversation(room.conversation_id, db, user)


@app.post("/api/v1/conversations/{conversation_id}/assist", response_model=AssistResponse)
async def assist_conversation(
    conversation_id: str,
    request: AssistRequest,
    db: Session = Depends(get_db),
    user: AnonymousUser = Depends(get_current_user),
) -> AssistResponse:
    require_participant(db, conversation_id, user.id)
    conversation = db.get(Conversation, conversation_id)
    messages = db.scalars(select(Message).where(
        Message.conversation_id == conversation_id,
    ).order_by(Message.sequence.asc())).all()
    history = [{"role": item.role, "content": item.content} for item in messages]
    suggestion = await LLMService().assist(request.kind, conversation.emotion_label, history, request.draft)
    if request.kind == "summary":
        summary = db.scalar(select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.user_id == user.id,
        ))
        if summary:
            summary.content = suggestion
        else:
            db.add(ConversationSummary(conversation_id=conversation_id, user_id=user.id, content=suggestion))
        db.commit()
    return AssistResponse(kind=request.kind, suggestion=suggestion)


@app.get("/api/v1/me/emotions", response_model=list[EmotionHistoryItem])
def emotion_history(db: Session = Depends(get_db), user: AnonymousUser = Depends(get_current_user)) -> list[EmotionHistoryItem]:
    entries = db.scalars(select(EmotionEntry).where(
        EmotionEntry.user_id == user.id,
    ).order_by(EmotionEntry.created_at.desc()).limit(100)).all()
    return [EmotionHistoryItem(
        id=item.id, primary_emotion=item.primary_emotion, intensity=item.intensity,
        valence=item.valence, arousal=item.arousal, explanation=item.explanation,
        created_at=item.created_at,
    ) for item in entries]


@app.get("/api/v1/me/conversations", response_model=list[ConversationHistoryItem])
def conversation_history(db: Session = Depends(get_db), user: AnonymousUser = Depends(get_current_user)) -> list[ConversationHistoryItem]:
    rows = db.execute(select(Conversation, Participant).join(
        Participant, Participant.conversation_id == Conversation.id,
    ).where(
        Participant.user_id == user.id, Participant.hidden_at.is_(None),
    ).order_by(Conversation.created_at.desc()).limit(100)).all()
    result: list[ConversationHistoryItem] = []
    for conversation, _ in rows:
        peers = db.scalars(select(Participant.nickname).where(
            Participant.conversation_id == conversation.id,
            Participant.user_id != user.id,
        )).all()
        summary = db.scalar(select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation.id,
            ConversationSummary.user_id == user.id,
        ))
        result.append(ConversationHistoryItem(
            id=conversation.id, kind=conversation.kind, emotion_label=conversation.emotion_label,
            status=conversation.status, created_at=conversation.created_at,
            summary=summary.content if summary else None, peer_names=list(peers),
        ))
    return result


@app.delete("/api/v1/me/conversations/{conversation_id}")
def hide_conversation(conversation_id: str, db: Session = Depends(get_db), user: AnonymousUser = Depends(get_current_user)) -> dict:
    participant = db.scalar(select(Participant).where(
        Participant.conversation_id == conversation_id, Participant.user_id == user.id,
    ))
    if not participant:
        raise HTTPException(404, "会话不存在")
    participant.hidden_at = datetime.utcnow()
    db.commit()
    return {"status": "hidden"}


@app.delete("/api/v1/me/history")
def clear_history(db: Session = Depends(get_db), user: AnonymousUser = Depends(get_current_user)) -> dict:
    for participant in db.scalars(select(Participant).where(Participant.user_id == user.id)):
        participant.hidden_at = datetime.utcnow()
    for entry in db.scalars(select(EmotionEntry).where(EmotionEntry.user_id == user.id)):
        db.delete(entry)
    db.commit()
    return {"status": "cleared"}


@app.websocket("/api/v1/ws/conversations/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: str) -> None:
    protocols = [item.strip() for item in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    token_protocol = next((item for item in protocols if item.startswith("token.")), "")
    token = token_protocol.removeprefix("token.")
    with SessionLocal() as db:
        device = db.scalar(select(DeviceSession).where(DeviceSession.token == token, DeviceSession.revoked_at.is_(None)))
        user = db.get(AnonymousUser, device.user_id) if device else db.scalar(select(AnonymousUser).where(AnonymousUser.token == token))
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
