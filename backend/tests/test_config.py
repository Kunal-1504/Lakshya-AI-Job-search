from pathlib import Path

import pytest
from lakshya.config import Settings, load_settings
from pydantic import ValidationError


def test_environment_secrets_and_relative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.yaml"
    path.write_text("data_dir: storage\ndatabase_url: sqlite:///storage/jobs.db\n")
    monkeypatch.setenv("LAKSHYA_API_KEY", "key-from-environment")
    settings = load_settings(path)
    assert settings.data_dir == tmp_path / "storage"
    assert str(tmp_path / "storage/jobs.db") in settings.database_url
    assert settings.api_key.get_secret_value() == "key-from-environment"
    assert "key-from-environment" not in str(settings.public_summary())
    assert "api_key" not in settings.model_dump()


def test_yaml_cannot_supply_secrets(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("api_key: forbidden\n")
    with pytest.raises(ValueError, match="environment variables"):
        load_settings(path)


@pytest.mark.parametrize(
    "values",
    [
        {"freshness_hours": 25},
        {"max_experience_years": 3},
        {"match_threshold": 101},
        {"max_agent_iterations": 4},
        {"request_delay_min_seconds": 2},
        {"request_delay_min_seconds": 6, "request_delay_max_seconds": 3},
        {"max_run_tokens": 1000, "max_day_tokens": 999},
        {"environment": "production"},
        {"unknown_setting": True},
    ],
)
def test_invalid_settings_rejected(values):
    with pytest.raises(ValidationError):
        Settings.model_validate(values)
