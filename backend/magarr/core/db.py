"""Database engine, declarative base and migrations."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import DateTime, Engine, MetaData, create_engine, event, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger(__name__)

# Deterministic constraint names keep Alembic batch migrations on SQLite sane.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ModelBase(Base):
    """Abstract base for domain tables: integer id plus created/updated timestamps."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def create_db_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", _set_sqlite_pragmas)
        return engine
    return create_engine(url, pool_pre_ping=True)


def sqlite_path(url: str) -> Path | None:
    """The database file for a file-based SQLite URL, else None."""
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        return Path(url.removeprefix("sqlite:///"))
    return None


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def alembic_config() -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(files("magarr") / "migrations"))
    return cfg


class MigrationError(RuntimeError):
    pass


def _pending(engine: Engine, cfg: AlembicConfig) -> tuple[str | None, str]:
    head = ScriptDirectory.from_config(cfg).get_current_head()
    return current_revision(engine), head


def _backup_sqlite(engine: Engine, current: str | None, head: str) -> Path | None:
    """Copy the database file before upgrading, so a failed migration can be rolled back."""
    database = engine.url.database
    if engine.dialect.name != "sqlite" or not database or database == ":memory:":
        return None
    source = Path(database)
    if not source.exists() or current is None:
        return None  # a brand-new database has nothing to protect
    target = source.with_name(f"{source.name}.pre-{head}-from-{current}.bak")
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)  # consistent copy even with WAL
    return target


def run_migrations(engine: Engine) -> None:
    cfg = alembic_config()
    current, head = _pending(engine, cfg)
    if current == head:
        return
    backup = _backup_sqlite(engine, current, head)
    if backup:
        logger.info("Backed up the database before migrating", extra={"backup": str(backup)})

    with engine.connect() as connection:
        sqlite = engine.dialect.name == "sqlite"
        if sqlite:
            # SQLite batch migrations rebuild tables (copy, drop, rename). With foreign keys
            # enforced, dropping a table other rows reference fails, so switch enforcement off
            # for the migration (it is ignored inside a transaction, hence before begin) and
            # verify integrity afterwards.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()  # end SQLAlchemy's autobegun transaction before our own
        try:
            with connection.begin():
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
                if sqlite and (
                    problems := connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                ):
                    raise MigrationError(f"Migration left broken foreign keys: {problems[:5]}")
        finally:
            if sqlite:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
