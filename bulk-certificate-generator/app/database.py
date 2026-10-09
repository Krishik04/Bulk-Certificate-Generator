"""Database engine, session factory and the FastAPI session dependency."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_db_engine(database_url: str) -> Engine:
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Background tasks run in a worker thread, so the SQLite connection
        # must be usable from a thread other than the one that created it.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create tables if they do not exist (sufficient for local development)."""
    from app import models  # noqa: F401  -- registers the models on Base.metadata

    Base.metadata.create_all(bind=engine)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per API request, always closed afterwards."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
