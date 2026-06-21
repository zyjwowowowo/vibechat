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
    expires_persistently,
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


def emotion_complementarity(a: EmotionEntry, b: EmotionEntry) -> float:
    """Prefer shared context plus a gently balancing energy, never raw emotional opposition."""
    words_a, words_b = set(a.keywords), set(b.keywords)
    topic = len(words_a & words_b) / len(words_a | words_b) if words_a | words_b else 0
    distribution = _cosine(a.distribution, b.distribution)
    arousal_gap = abs(a.arousal - b.arousal)
    balance = max(0.0, 1 - abs(arousal_gap - 0.3) / 0.7)
    valence_safety = 1.0 if max(a.valence, b.valence) > -0.6 else 0.35
    intensity_fit = 1 - abs(a.intensity - b.intensity)
    return round(0.3 * topic + 0.25 * distribution + 0.25 * balance + 0.1 * valence_safety + 0.1 * intensity_fit, 4)


def create_human_conversation(
    db: Session,
    first: MatchTicket,
    second: MatchTicket,
    first_user: AnonymousUser,
    second_user: AnonymousUser,
    emotion_label: str,
    score: float,
) -> Conversation:
    persistent = bool(first_user.account_id and second_user.account_id)
    conversation = Conversation(
        kind="direct", emotion_label=emotion_label, match_score=score,
        expires_at=expires_persistently() if persistent else None,
    ) if persistent else Conversation(kind="direct", emotion_label=emotion_label, match_score=score)
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
    conversation = Conversation(
        kind="ai", emotion_label=emotion.primary_emotion, match_score=None,
        **({"expires_at": expires_persistently()} if user.account_id else {}),
    )
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


def create_group_conversation(
    db: Session,
    tickets: list[MatchTicket],
    users: list[AnonymousUser],
    emotion_label: str,
) -> Conversation:
    persistent = all(user.account_id for user in users)
    conversation = Conversation(
        kind="private_group",
        emotion_label=emotion_label,
        match_score=None,
        **({"expires_at": expires_persistently()} if persistent else {}),
    )
    db.add(conversation)
    db.flush()
    db.add_all([
        Participant(
            conversation_id=conversation.id,
            user_id=user.id,
            nickname=user.nickname,
            avatar_seed=user.avatar_seed,
        ) for user in users
    ])
    for ticket in tickets:
        ticket.status = "matched"
        ticket.conversation_id = conversation.id
    return conversation


def enqueue_and_match(db: Session, user: AnonymousUser, emotion: EmotionEntry, mode: str = "similar") -> MatchTicket:
    existing = db.scalar(
        select(MatchTicket).where(MatchTicket.user_id == user.id, MatchTicket.status == "waiting")
    )
    if existing:
        existing.status = "cancelled"

    ticket = MatchTicket(user_id=user.id, emotion_id=emotion.id, mode=mode)
    db.add(ticket)
    db.flush()

    candidates = db.execute(
        select(MatchTicket, EmotionEntry, AnonymousUser)
        .join(EmotionEntry, MatchTicket.emotion_id == EmotionEntry.id)
        .join(AnonymousUser, MatchTicket.user_id == AnonymousUser.id)
        .where(
            MatchTicket.status == "waiting",
            MatchTicket.mode == mode,
            MatchTicket.user_id != user.id,
            MatchTicket.expires_at > datetime.utcnow(),
        )
        .order_by(MatchTicket.created_at.asc())
        .with_for_update(skip_locked=True)
    ).all()

    if mode == "private_group":
        compatible: list[tuple[MatchTicket, EmotionEntry, AnonymousUser, float]] = []
        for candidate, candidate_emotion, candidate_user in candidates:
            score = emotion_similarity(emotion, candidate_emotion)
            if score >= 0.52:
                compatible.append((candidate, candidate_emotion, candidate_user, score))
        compatible.sort(key=lambda item: item[3], reverse=True)
        if len(compatible) >= 2:
            chosen = compatible[:5]
            create_group_conversation(
                db,
                [item[0] for item in chosen] + [ticket],
                [item[2] for item in chosen] + [user],
                emotion.primary_emotion,
            )
        db.commit()
        db.refresh(ticket)
        return ticket

    best: tuple[MatchTicket, EmotionEntry, AnonymousUser, float] | None = None
    for candidate, candidate_emotion, candidate_user in candidates:
        score = emotion_complementarity(emotion, candidate_emotion) if mode == "complementary" else emotion_similarity(emotion, candidate_emotion)
        threshold = 0.48 if mode == "complementary" else 0.65
        if score >= threshold and (best is None or score > best[3]):
            best = (candidate, candidate_emotion, candidate_user, score)

    if best:
        candidate, _, candidate_user, score = best
        create_human_conversation(
            db, candidate, ticket, candidate_user, user, emotion.primary_emotion, score
        )
    db.commit()
    db.refresh(ticket)
    return ticket
