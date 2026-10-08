import json

import structlog
from lakshya.logging import configure_logging, redact


def test_recursive_redaction_and_json_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-sensitive-secret")
    value = redact({"nested": [{"api_key": "other", "message": "key=test-sensitive-secret"}]})
    assert value["nested"][0] == {"api_key": "[REDACTED]", "message": "key=[REDACTED]"}
    file = tmp_path / "events.jsonl"
    configure_logging(file)
    structlog.get_logger().info(
        "agent_step", tool="http", password="secret", input_summary={"job_id": "1"}
    )
    event = json.loads(file.read_text().splitlines()[-1])
    assert event["password"] == "[REDACTED]"
    assert event["tool"] == "http" and event["timestamp"]
