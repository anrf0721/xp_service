from xp_owner_service.app.repositories import conversation as repository
from xp_owner_service.common import Rejected, new_id, now


def open_locked(db, credential_id):
    # ON CONFLICT waits for a competing first transaction. At READ COMMITTED the
    # following SELECT sees its committed winner and locks that exact row.
    repository.insert_open(db, id=new_id(), credential_id=credential_id, mode="AI", input_revision=0, created_at=now())
    conv = repository.lock_open(db, credential_id)
    if conv is None:
        raise Rejected("没有未结束会话")
    return conv


def current(factory, identity):
    with factory() as db, db.begin():
        conv = repository.get_open(db, identity["credential_id"])
        return {"会话编号": None if conv is None else conv.id, "会话版本": None if conv is None else conv.input_revision}
