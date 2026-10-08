import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from lakshya.db.base import Base
from lakshya.db.migrate import migration_config
from lakshya.db.models import ApplicationRecord, JobRecord, StatusHistory
from lakshya.db.seed import seed_demo
from lakshya.db.session import build_engine
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError


def test_migration_matches_models_and_reverses(settings, database):
    engine = build_engine(settings)
    with engine.connect() as connection:
        migration = MigrationContext.configure(connection)
        assert migration.get_current_revision() == "0001_foundations"
        assert compare_metadata(migration, Base.metadata) == []
    command.downgrade(migration_config(settings), "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    command.upgrade(migration_config(settings), "head")
    assert set(Base.metadata.tables).issubset(inspect(engine).get_table_names())
    engine.dispose()


def test_seed_is_idempotent_and_has_history(database):
    with database() as session, session.begin():
        assert seed_demo(session) == 3
        assert seed_demo(session) == 0
    with database() as session:
        assert session.scalar(select(func.count()).select_from(JobRecord)) == 3
        assert session.scalar(select(func.count()).select_from(StatusHistory)) == 3
        jobs = list(session.scalars(select(JobRecord)))
        assert all(job.is_demo and job.posted_at.tzinfo is not None for job in jobs)


def test_duplicate_application_key_and_foreign_keys_enforced(database):
    with database() as session, session.begin():
        seed_demo(session)
    with database() as session:
        application = session.scalar(select(ApplicationRecord))
        other_job = session.scalar(select(JobRecord).where(JobRecord.id != application.job_id))
        key = application.application_key
        other_id = other_job.id
    with pytest.raises(IntegrityError), database() as session, session.begin():
        session.add(ApplicationRecord(job_id=other_id, application_key=key))
        session.flush()
    with pytest.raises(IntegrityError), database() as session, session.begin():
        session.add(ApplicationRecord(job_id="missing-job", application_key="different"))
        session.flush()
