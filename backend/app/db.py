"""SQLite engine and session dependency."""
from __future__ import annotations

from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            connect_args={"check_same_thread": False},
        )
    return _engine


def set_engine(engine) -> None:
    """Override the engine (used by tests)."""
    global _engine
    _engine = engine


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
