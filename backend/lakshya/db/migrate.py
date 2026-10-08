import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from lakshya.config import Settings


def migration_config(settings: Settings, root: Path | None = None) -> Config:
    if root is None:
        candidates = [
            Path(os.getenv("LAKSHYA_PROJECT_ROOT", str(Path.cwd()))),
            Path(__file__).resolve().parents[3],
        ]
        root = next((path for path in candidates if (path / "alembic.ini").is_file()), None)
    if root is None:
        raise FileNotFoundError("Run from the project root or set LAKSHYA_PROJECT_ROOT to it")
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/migrations"))
    # Pass the URL as an attribute to avoid ConfigParser interpolation of '%' in passwords.
    config.attributes["database_url"] = settings.database_url
    return config


def upgrade_database(settings: Settings) -> None:
    from lakshya.db.session import build_engine

    engine = build_engine(settings)
    engine.dispose()
    command.upgrade(migration_config(settings), "head")
