import math
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AnonymousUser,
    Conversation,
    EmotionEntry,
    MatchTicket,
    Participant,
)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) | set(b)
    dot = sum(float(a.get(k, 0)) * float(b.get(k, 0)) for k in keys)
    norm_a = math.sqrt(sum(float(a.get(k, 0)) ** 2 for k in keys))
    norm_b = math.sqrt(sum(float(b.get(k, 0)) ** 2 for k in keys))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def emotion_similarity(a: EmotionEntry, b: EmotionEntry) -> float:
    distribution = _cosine(a.distribution, b.distribution)
    valence = 1 - abs(a.valence - b.valence) / 2
    arousal = 1 - abs(a.arousal - b.arousal)
    intensity = 1 - abs(a.intensity - b.intensity)
    words_a, words_b = set(a.keywords), set(b.keywords)
    keyword = len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 0
    return round(0.5 * distribution + 0.2 * valence + 0.15 * arousal + 0.1 * intensity + 0.05 * keyword, 4)


def create_human_conversation(
    db: Session,
    first: MatchTicket,
    second: MatchTicket,
    first_user: AnonymousUser,
    second_user: AnonymousUser,
    emotion_label: str,
    score: float,
) -> Conversation:
    conversation = Conversation(kind="human", emotion_label=emotion_label, match_score=score)
    db.add(conversation)
    db.flush()
    db.add_all(
        [
            Participant(
                conversation_id=conversation.id,
                user_id=first_user.id,
                nickname=first_user.nickname,
                avatar_seed=first_user.avatar_seed,
            ),
            Participant(
                conversation_id=conversation.id,
                user_id=second_user.id,
                nickname=second_user.nickname,
                avatar_seed=second_user.avatar_seed,
            ),
        ]
    )
    for ticket in (first, second):
        ticket.status = "matched"
        ticket.conversation_id = conversation.id
        ticket.match_score = score
    return conversation


def create_ai_conversation(db: Session, ticket: MatchTicket, user: AnonymousUser, emotion: EmotionEntry) -> Conversation:
    conversation = Conversation(kind="ai", emotion_label=emotion.primary_emotion, match_score=None)
    db.add(conversation)
    db.flush()
    db.add_all(
        [
            Participant(
                conversation_id=conversation.id,
                user_id=user.id,
                nickname=user.nickname,
                avatar_seed=user.avatar_seed,
            ),
            Participant(
                conversation_id=conversation.id,
                user_id=None,
                nickname="月光水獭 · AI",
                avatar_seed="moon-otter",
                is_ai=True,
            ),
        ]
    )
    ticket.status = "matched"
    ticket.conversation_id = conversation.id
    return conversation


def enqueue_and_match(db: Session, user: AnonymousUser, emotion: EmotionEntry) -> MatchTicket:
    existing = db.scalar(
        select(MatchTicket).where(MatchTicket.user_id == user.id, MatchTicket.status == "waiting")
    )
    if existing:
        existing.status = "cancelled"

    ticket = MatchTicket(user_id=user.id, emotion_id=emotion.id)
    db.add(ticket)
    db.flush()

    candidates = db.execute(
        select(MatchTicket, EmotionEntry, AnonymousUser)
        .join(EmotionEntry, MatchTicket.emotion_id == EmotionEntry.id)
        .join(AnonymousUser, MatchTicket.user_id == AnonymousUser.id)
        .where(
            MatchTicket.status == "waiting",
            MatchTicket.user_id != user.id,
            MatchTicket.expires_at > datetime.utcnow(),
        )
        .order_by(MatchTicket.created_at.asc())
        .with_for_update(skip_locked=True)
    ).all()

    best: tuple[MatchTicket, EmotionEntry, AnonymousUser, float] | None = None
    for candidate, candidate_emotion, candidate_user in candidates:
        score = emotion_similarity(emotion, candidate_emotion)
        if score >= 0.65 and (best is None or score > best[3]):
            best = (candidate, candidate_emotion, candidate_user, score)

    if best:
        candidate, _, candidate_user, score = best
        create_human_conversation(
            db, candidate, ticket, candidate_user, user, emotion.primary_emotion, score
        )
    db.commit()
    db.refresh(ticket)
    return ticket

