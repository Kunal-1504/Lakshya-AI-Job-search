from pathlib import Path

import pytest
from lakshya.config import Settings
from lakshya.db.migrate import upgrade_database
from lakshya.db.session import build_engine, session_factory
from pydantic import SecretStr


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        log_file=tmp_path / "test.jsonl",
        api_key=SecretStr("test-api-key"),
    )


@pytest.fixture
def database(settings: Settings):
    upgrade_database(settings)
    engine = build_engine(settings)
    yield session_factory(engine)
    engine.dispose()
