import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


@lru_cache
def engine():
    url = make_url(os.environ["XP_OWNER_DATABASE_URL"])
    if url.get_backend_name() != "postgresql" or url.database == "customer_service":
        raise RuntimeError("A dedicated PostgreSQL owner database is required")
    return create_engine(url, hide_parameters=True, pool_pre_ping=True)


@lru_cache
def sessions():
    return sessionmaker(engine(), expire_on_commit=False)


def initialize():
    from xp_owner_service.models import Base
    Base.metadata.create_all(engine())
