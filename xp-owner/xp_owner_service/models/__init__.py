from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    credential_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    input_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("mode IN ('AI','QUEUED','HUMAN','CLOSED')"),
        Index("uq_open_conversation_credential", "credential_id", unique=True, postgresql_where=text("mode <> 'CLOSED'")),
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    credential_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("conversation_id", "client_request_id"), UniqueConstraint("conversation_id", "revision"))


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    collect_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_collect_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_revision: Mapped[int | None] = mapped_column(Integer)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    current_claim_id: Mapped[str | None] = mapped_column(String(64))
    invalidated_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("status IN ('COLLECTING','RUNNING','ATTENTION','SUPERSEDED','INVALIDATED','PUBLISHED','TIMED_OUT','FAILED')"),
        CheckConstraint("attempts BETWEEN 0 AND 3"),
        Index("uq_collecting_turn", "conversation_id", unique=True, postgresql_where=text("status = 'COLLECTING'")),
        Index("uq_running_turn", "conversation_id", unique=True, postgresql_where=text("status = 'RUNNING'")),
    )


class TurnMessage(Base):
    __tablename__ = "turn_messages"
    turn_id: Mapped[str] = mapped_column(ForeignKey("conversation_turns.id"), primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), primary_key=True, unique=True)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turn_id: Mapped[str] = mapped_column(ForeignKey("conversation_turns.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    snapshot_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64))
    cited_version_id: Mapped[str | None] = mapped_column(String(128))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("turn_id", "ordinal"), CheckConstraint("ordinal BETWEEN 1 AND 3"))


class PublishedReply(Base):
    __tablename__ = "published_replies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    turn_id: Mapped[str] = mapped_column(ForeignKey("conversation_turns.id"), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Handoff(Base):
    __tablename__ = "handoffs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), unique=True, nullable=False)
    advisor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationEvent(Base):
    __tablename__ = "conversation_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RealtimeOutbox(Base):
    __tablename__ = "realtime_outbox"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("conversation_events.id"), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
