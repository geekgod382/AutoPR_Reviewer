from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from app.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    db_url = settings.database_url

    if db_url.startswith("sqlite"):
        return create_engine(db_url, connect_args={"check_same_thread": False})
    else:
        return create_engine(db_url, pool_pre_ping=True)

def get_session() -> Session:
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def create_tables():
    from app.models import Installation, Subscription, ReviewLog  # noqa: F401
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
