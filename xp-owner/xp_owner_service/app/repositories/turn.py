from sqlalchemy import select, update

from xp_owner_service.models import Claim, Conversation, ConversationTurn, PublishedReply


def collecting(db, conversation_id):
    return db.scalar(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id, ConversationTurn.status == "COLLECTING").with_for_update())


def running(db, conversation_id):
    return db.scalar(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id, ConversationTurn.status == "RUNNING").with_for_update())


def lock(db, turn_id):
    return db.scalar(select(ConversationTurn).where(ConversationTurn.id == turn_id).with_for_update().execution_options(populate_existing=True))


def get(db, turn_id):
    return db.get(ConversationTurn, turn_id)


def claim(db, claim_id):
    return db.get(Claim, claim_id)


def insert(db, row):
    db.add(row)
    db.flush()
    return row


def unfinished(db, conversation_id):
    return list(db.scalars(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id, ConversationTurn.status.in_(["COLLECTING", "RUNNING"])).with_for_update()))


def published(db, turn_id):
    return db.scalar(select(PublishedReply).where(PublishedReply.turn_id == turn_id))


def conditional_claim(db, turn_id, previous_status, previous_claim, attempt, **values):
    return db.execute(update(ConversationTurn).where(
        ConversationTurn.id == turn_id, ConversationTurn.status == previous_status,
        ConversationTurn.current_claim_id == previous_claim, ConversationTurn.attempts == attempt,
    ).values(**values).returning(ConversationTurn.id)).scalar_one_or_none()


def candidate_conversations(db, at):
    return list(db.scalars(select(ConversationTurn.conversation_id).join(Conversation, Conversation.id == ConversationTurn.conversation_id).where(
        Conversation.mode == "AI",
        ((ConversationTurn.status == "COLLECTING") & (ConversationTurn.collect_until <= at)) |
        ((ConversationTurn.status == "RUNNING") & (ConversationTurn.locked_until <= at)),
    ).distinct().order_by(ConversationTurn.conversation_id)))
