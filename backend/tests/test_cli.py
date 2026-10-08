from lakshya.cli import app
from typer.testing import CliRunner


def test_cli_invalid_settings_does_not_leak_environment_secrets(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("match_threshold: 150\n")
    monkeypatch.setenv("LAKSHYA_API_KEY", "private-secret-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-anthropic-value")
    result = CliRunner().invoke(app, ["--config", str(path), "doctor"])
    assert result.exit_code == 1
    assert "private-secret-value" not in result.output
    assert "private-anthropic-value" not in result.output
