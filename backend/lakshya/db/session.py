from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from lakshya.config import Settings


def build_engine(settings: Settings) -> Engine:
    url = make_url(settings.database_url)
    sqlite = url.get_backend_name() == "sqlite"
    if sqlite and url.database and url.database != ":memory:":
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"check_same_thread": False, "timeout": 30} if sqlite else {}
    engine = create_engine(url, connect_args=kwargs, pool_pre_ping=True)
    if sqlite:

        @event.listens_for(engine, "connect")
        def pragmas(connection: object, record: object) -> None:
            import sqlite3

            if isinstance(connection, sqlite3.Connection):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                if url.database != ":memory:":
                    cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def transactional_session(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    with factory() as session, session.begin():
        yield session
