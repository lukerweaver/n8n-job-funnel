import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_SQLITE_PATH = Path("./data/jobs.db")


def _default_database_url() -> str:
    if override := os.getenv("DATABASE_URL"):
        return override

    return f"sqlite:///{DEFAULT_SQLITE_PATH.resolve()}"


DATABASE_URL = _default_database_url()

if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    # For absolute Windows-style or POSIX paths (e.g. sqlite:////app/data/jobs.db),
    # preserve leading slash. For relative paths, remove the optional leading
    # ./ component to keep Path behavior consistent.
    if db_path.startswith("./"):
        db_path = db_path.removeprefix("./")
    parent_dir = Path(db_path).expanduser().parent
    if str(parent_dir) not in {"", ".", "/"}:
        parent_dir.mkdir(parents=True, exist_ok=True)

class Base(DeclarativeBase):
    pass


connect_args = {
    "check_same_thread": False,
    "timeout": 60,
} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(connection, _connection_record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA journal_mode=DELETE")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
