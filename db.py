from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    return create_engine(url, future=True, pool_pre_ping=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)
