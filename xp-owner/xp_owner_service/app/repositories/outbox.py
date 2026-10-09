from sqlalchemy import select

from xp_owner_service.models import ConversationEvent, RealtimeOutbox


def insert_event(db, event):
    db.add(event)
    db.flush()
    return event


def insert_outbox(db, row):
    db.add(row)
    db.flush()


def events_after(db, conversation_id, after_seq):
    return list(db.scalars(select(ConversationEvent).where(ConversationEvent.conversation_id == conversation_id, ConversationEvent.sequence > after_seq).order_by(ConversationEvent.sequence)))
