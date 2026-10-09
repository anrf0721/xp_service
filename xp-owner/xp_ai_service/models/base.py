"""Declarative base. Models do not open connections or create schema."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
