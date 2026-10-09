"""Declarative base. This module defines no tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
