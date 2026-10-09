"""Credential table. Stores an irreversible secret digest, never plaintext."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from xp_account_service.models.base import Base


class Credential(Base):
    __tablename__ = "credentials"

    credential_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
