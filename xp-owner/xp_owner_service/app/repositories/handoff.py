from sqlalchemy import select

from xp_owner_service.models import Handoff


def get(db, conversation_id):
    return db.scalar(select(Handoff).where(Handoff.conversation_id == conversation_id))


def insert(db, row):
    db.add(row)
    db.flush()
