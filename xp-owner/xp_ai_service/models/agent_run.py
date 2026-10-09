"""Copied run text. request_id is unique. No caller-supplied failure flags."""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from xp_ai_service.models.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("request_id", name="uq_agent_runs_request_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_id: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    flow_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cited_version_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    boundary: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
