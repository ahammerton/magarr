from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, String, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column

from magarr.core.db import (
    Base,
    ModelBase,
    alembic_config,
    create_db_engine,
    create_session_factory,
    current_revision,
    run_migrations,
)
from magarr.core.repository import Repository

# A throwaway model on its own metadata, so it never leaks into the app's migrations.
_test_metadata = MetaData()


class _TestBase(ModelBase):
    __abstract__ = True
    metadata = _test_metadata


class Widget(_TestBase):
    __tablename__ = "widgets"
    name: Mapped[str] = mapped_column(String(50))


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_db_engine("sqlite:///:memory:")
    _test_metadata.create_all(engine)
    with create_session_factory(engine)() as db_session:
        yield db_session


def test_migrations_upgrade_fresh_database(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'sub' / 'magarr.db'}")
    run_migrations(engine)
    run_migrations(engine)  # idempotent
    assert current_revision(engine) == _head()
    assert "alembic_version" in inspect(engine).get_table_names()


def _head() -> str:
    [head] = ScriptDirectory.from_config(alembic_config()).get_heads()
    return head


def test_single_migration_head() -> None:
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def test_models_match_migrations(tmp_path: Path) -> None:
    """Fails if a model changes without a matching Alembic migration."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'magarr.db'}")
    run_migrations(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_sqlite_pragmas(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'magarr.db'}")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_repository_crud(session: Session) -> None:
    repo = Repository(session, Widget)

    widget = repo.add(Widget(name="first"))
    assert widget.id is not None
    assert widget.created_at is not None
    assert repo.get(widget.id) is widget

    repo.update(widget, name="renamed")
    assert repo.get(widget.id).name == "renamed"
    with pytest.raises(AttributeError):
        repo.update(widget, nonsense=1)

    repo.delete(widget)
    assert repo.get(widget.id) is None


def test_repository_pagination(session: Session) -> None:
    repo = Repository(session, Widget)
    for i in range(7):
        repo.add(Widget(name=f"w{i}"))

    page = repo.list(page=2, page_size=3)
    assert page.total == 7
    assert [w.name for w in page.items] == ["w3", "w4", "w5"]
    assert len(repo.list(page=3, page_size=3).items) == 1
    assert repo.list(page=0, page_size=0).page_size == 1


def test_repository_subclass_declares_model(session: Session) -> None:
    class WidgetRepository(Repository[Widget]):
        model = Widget

    repo = WidgetRepository(session)
    repo.add(Widget(name="x"))
    assert repo.list().total == 1


def _populated_at_0003(path: Path):
    """A database like a real Phase 2 install: a magazine that references the quality profile."""
    from alembic import command
    from sqlalchemy import text

    engine = create_db_engine(f"sqlite:///{path}")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0003")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO root_folders (id, path, is_default, created_at, updated_at) VALUES (1, '/m', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO quality_profiles (id, name, created_at, updated_at) VALUES (1, 'Any', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO quality_profile_items (profile_id, quality, allowed, upgrade_until, position, created_at, updated_at) VALUES (1, 'pdf', 1, 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO magazines (id, title, sort_title, alternate_titles, language, frequency, tags, quality_profile_id,"
                " root_folder_id, folder, monitored, created_at, updated_at) VALUES (1, 'NG', 'ng', '[]', 'en', 'monthly', '[]', 1, 1, 'NG', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO issues (magazine_id, issue_number, sort_index, monitored, status, created_at, updated_at) VALUES (1, '2025-01', 1, 1, 'wanted', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    return engine


def test_upgrade_with_rows_referencing_rebuilt_tables(tmp_path: Path) -> None:
    """Regression: 0004 rebuilds quality_profiles; with foreign keys enforced, the referenced
    table could not be dropped, leaving a half-applied migration (real user database)."""
    from sqlalchemy import text

    engine = _populated_at_0003(tmp_path / "magarr.db")
    run_migrations(engine)
    assert current_revision(engine) == _head()
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT protocols FROM quality_profiles")).scalar()
            == '["usenet", "torrent"]'
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM magazines WHERE quality_profile_id = 1")
            ).scalar()
            == 1
        )
        assert conn.execute(text("SELECT count(*) FROM issues")).scalar() == 1
        # Enforcement is back on for normal use, and nothing dangles.
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def test_migrations_back_up_the_database_first(tmp_path: Path) -> None:
    db = tmp_path / "magarr.db"
    engine = _populated_at_0003(db)
    run_migrations(engine)
    backups = list(tmp_path.glob("magarr.db.pre-*.bak"))
    assert [b.name for b in backups] == [f"magarr.db.pre-{_head()}-from-0003.bak"]
    run_migrations(engine)  # nothing pending: no new backup
    assert len(list(tmp_path.glob("magarr.db.pre-*.bak"))) == 1


def test_flat_folder_migration_only_changes_the_old_default(tmp_path: Path) -> None:
    from alembic import command
    from sqlalchemy import text

    for stored, expected in (("Season {year}", ""), ("{year}", "{year}")):
        engine = create_db_engine(f"sqlite:///{tmp_path / (expected or 'old')}.db")
        cfg = alembic_config()
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0005")
            conn.execute(
                text(
                    "INSERT INTO naming_config (magazine_folder_pattern, year_folder_pattern, issue_file_pattern,"
                    " replace_illegal_characters, colon_replacement, created_at, updated_at)"
                    " VALUES ('{magazine_title}', :y, '{issue_number}', 1, ' -', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"y": stored},
            )
        run_migrations(engine)
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT year_folder_pattern FROM naming_config")).scalar()
                == expected
            )
