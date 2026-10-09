from sqlalchemy import select

from xp_owner_service.models import Message, TurnMessage


def get_request(db, conversation_id, request_id):
    return db.scalar(select(Message).where(Message.conversation_id == conversation_id, Message.client_request_id == request_id))


def insert(db, message):
    db.add(message)
    db.flush()
    return message


def attach(db, turn_id, message_id):
    db.add(TurnMessage(turn_id=turn_id, message_id=message_id))
    db.flush()


def for_turn(db, turn_id):
    return list(db.scalars(select(Message).join(TurnMessage, TurnMessage.message_id == Message.id).where(TurnMessage.turn_id == turn_id).order_by(Message.revision)))
