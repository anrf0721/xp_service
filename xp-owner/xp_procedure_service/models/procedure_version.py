"""Procedure version table and the one-current-version partial unique index."""

from sqlalchemy import Boolean, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from xp_procedure_service.models.base import Base


class ProcedureVersion(Base):
    __tablename__ = "procedure_versions"
    __table_args__ = (
        Index(
            "uq_procedure_versions_current_flow_key",
            "flow_key",
            unique=True,
            postgresql_where=text("current_published"),
        ),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_label: Mapped[str] = mapped_column(String(128), nullable=False)
    flow_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    steps: Mapped[str] = mapped_column(Text, nullable=False)
    boundary: Mapped[str] = mapped_column(Text, nullable=False)
    current_published: Mapped[bool] = mapped_column(Boolean, nullable=False)
    withdrawn: Mapped[bool] = mapped_column(Boolean, nullable=False)
