from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from db import Base

CUSTOMER_KINDS = ("owner", "authorized_driver")
EXACT_BODY = "如何在 App 里预约保养"
FLOW_KEY = "App预约保养步骤"
FLOW_TITLE = "App 预约保养步骤"
FLOW_STEPS = "【非官方占位】此处不是小鹏官方步骤。上线前必须替换为人工审核原句。"
FLOW_BOUNDARY = "这只说明 App 里的预约步骤，不表示已经预约成功，也不表示这台车在保。"
FLOW_LABEL = "占位审核版"
COLLECT_PUSH_MS = 1500
COLLECT_CAP_MS = 8000
CLAIM_LEASE_MS = 20000
MAX_RECLAIMS = 1


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = {"schema": "owner_client"}
    credential_id = Column(Text, primary_key=True)
    kind = Column(Text, nullable=False)
    secret = Column(Text, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "kind IN ('owner', 'authorized_driver', 'advisor', 'admin')",
            name="credentials_kind",
        ),
        UniqueConstraint("secret", name="credentials_secret_key"),
        {"schema": "owner_client"},
    )


class Conversation(Base):
    __tablename__ = "conversations"
    session_id = Column(Text, primary_key=True)
    credential_id = Column(Text, ForeignKey("owner_client.credentials.credential_id"), nullable=False)
    sender_kind = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    bot_allowed = Column(Boolean, nullable=False)
    __table_args__ = (
        Index(
            "conversations_one_per_credential",
            "credential_id",
            unique=True,
        ),
        {"schema": "owner_client"},
    )


class UserMessage(Base):
    __tablename__ = "user_messages"
    message_id = Column(Text, primary_key=True)
    session_id = Column(Text, ForeignKey("owner_client.conversations.session_id"), nullable=False)
    client_request_id = Column(Text, nullable=False)
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    sender_kind = Column(Text, nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("session_id", "client_request_id", name="messages_request_key"),
        UniqueConstraint("session_id", "version", name="messages_version_key"),
        {"schema": "owner_client"},
    )


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    task_id = Column(Text, primary_key=True)
    session_id = Column(Text, ForeignKey("owner_client.conversations.session_id"), nullable=False)
    kind = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    opened_at = Column(DateTime(timezone=True), nullable=False)
    collect_until = Column(DateTime(timezone=True), nullable=True)
    claimed_version = Column(Integer, nullable=True)
    current_claim_id = Column(Text, nullable=True)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    reclaim_count = Column(Integer, nullable=False, server_default=text("0"))
    invalidated_reason = Column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "kind IN ('collecting', 'procedure', 'human')",
            name="tasks_kind",
        ),
        CheckConstraint(
            "status IN ('open', 'claimed', 'published', 'invalidated', 'attention')",
            name="tasks_status",
        ),
        Index(
            "tasks_one_open_collecting",
            "session_id",
            unique=True,
            postgresql_where=text("kind = 'collecting' AND status = 'open'"),
        ),
        {"schema": "owner_client"},
    )


class TaskMessage(Base):
    __tablename__ = "task_messages"
    task_id = Column(Text, ForeignKey("owner_client.follow_up_tasks.task_id"), primary_key=True)
    message_id = Column(Text, ForeignKey("owner_client.user_messages.message_id"), primary_key=True)
    position = Column(Integer, nullable=False)
    __table_args__ = {"schema": "owner_client"}


class Claim(Base):
    __tablename__ = "claims"
    claim_id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("owner_client.follow_up_tasks.task_id"), nullable=False)
    claimer = Column(Text, nullable=False)
    claimed_at = Column(DateTime(timezone=True), nullable=False)
    lease_until = Column(DateTime(timezone=True), nullable=False)
    input_version = Column(Integer, nullable=False)
    ordinal = Column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "ordinal", name="claims_ordinal_key"),
        CheckConstraint("ordinal IN (1, 2)", name="claims_ordinal_limit"),
        {"schema": "owner_client"},
    )


class ProcedureVersion(Base):
    __tablename__ = "procedure_versions"
    version_id = Column(Text, primary_key=True)
    flow_key = Column(Text, nullable=False)
    version_label = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    steps = Column(Text, nullable=False)
    boundary = Column(Text, nullable=False)
    current_published = Column(Boolean, nullable=False)
    withdrawn = Column(Boolean, nullable=False)
    __table_args__ = (
        Index(
            "procedure_one_current_per_key",
            "flow_key",
            unique=True,
            postgresql_where=text("current_published"),
        ),
        {"schema": "owner_client"},
    )


class RunRecord(Base):
    __tablename__ = "run_records"
    run_id = Column(Text, primary_key=True)
    claim_id = Column(Text, ForeignKey("owner_client.claims.claim_id"), nullable=False, unique=True)
    task_id = Column(Text, nullable=False)
    input_version = Column(Integer, nullable=False)
    cited_version_id = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    steps = Column(Text, nullable=True)
    boundary = Column(Text, nullable=True)
    version_label = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    state = Column(Text, nullable=False)
    __table_args__ = {"schema": "owner_client"}


class PublishedReply(Base):
    __tablename__ = "published_replies"
    reply_id = Column(Text, primary_key=True)
    task_id = Column(Text, ForeignKey("owner_client.follow_up_tasks.task_id"), nullable=False, unique=True)
    claim_id = Column(Text, nullable=False)
    run_id = Column(Text, nullable=False)
    session_id = Column(Text, nullable=False)
    input_version = Column(Integer, nullable=False)
    version_id = Column(Text, nullable=False)
    fields_json = Column(JSONB, nullable=False)
    __table_args__ = {"schema": "owner_client"}


class NoticeEvent(Base):
    __tablename__ = "notice_events"
    event_id = Column(Text, primary_key=True)
    session_id = Column(Text, ForeignKey("owner_client.conversations.session_id"), nullable=False)
    seq = Column(BigInteger, Identity(always=False), nullable=False)
    kind = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="events_seq_key"),
        {"schema": "owner_client"},
    )


class Takeover(Base):
    __tablename__ = "takeovers"
    session_id = Column(Text, primary_key=True)
    request_id = Column(Text, primary_key=True)
    __table_args__ = {"schema": "owner_client"}


class Refusal(Base):
    __tablename__ = "refusals"
    refusal_id = Column(Text, primary_key=True)
    credential_id = Column(Text, nullable=True)
    session_id = Column(Text, nullable=True)
    reason = Column(Text, nullable=False)
    refused_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = {"schema": "owner_client"}
