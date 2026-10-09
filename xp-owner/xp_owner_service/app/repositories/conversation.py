from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from xp_owner_service.models import Conversation


def insert_open(db, **values):
    return db.execute(
        insert(Conversation).values(**values).on_conflict_do_nothing(
            index_elements=[Conversation.credential_id], index_where=text("mode <> 'CLOSED'")
        ).returning(Conversation.id)
    ).scalar_one_or_none()


def lock_open(db, credential_id):
    return db.scalar(select(Conversation).where(Conversation.credential_id == credential_id, Conversation.mode != "CLOSED").with_for_update().execution_options(populate_existing=True))


def lock(db, conversation_id):
    return db.scalar(select(Conversation).where(Conversation.id == conversation_id).with_for_update().execution_options(populate_existing=True))


def get_open(db, credential_id):
    return db.scalar(select(Conversation).where(Conversation.credential_id == credential_id, Conversation.mode != "CLOSED"))


def enter_human(db, conversation_id):
    return db.execute(update(Conversation).where(Conversation.id == conversation_id, Conversation.mode == "AI").values(mode="HUMAN").returning(Conversation.id)).scalar_one_or_none()
