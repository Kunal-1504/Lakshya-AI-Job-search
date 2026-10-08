"""Cloud durability tests. PostgreSQL integration is opt-in against a test resource."""

import base64
import os
import secrets
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from lakshya.api.app import create_app
from lakshya.cloud import store
from lakshya.cloud.worker import process
from lakshya.db.models import PipelineRun
from lakshya.pipeline import Pipeline
from pydantic import SecretStr


def test_one_stage_checkpoints_resume_after_every_reopen(settings, database):
    identity = None
    stages = 0
    while stages < 20:
        pipeline = Pipeline(settings)
        try:
            if identity is None:
                identity = pipeline.start({"demo": True, "offline": True, "dry_run": True})
            pipeline.execute(identity, one_step=True)
            with database() as session:
                run = session.get(PipelineRun, identity)
                assert run
                if run.status == "completed":
                    assert run.result["ready"]
                    break
                assert run.status == "queued"
        finally:
            pipeline.close()
        stages += 1
    assert 8 <= stages < 20


@pytest.fixture
def cloud(settings, monkeypatch):
    if os.getenv("LAKSHYA_TEST_CLOUD") != "1":
        pytest.skip("Set LAKSHYA_TEST_CLOUD=1 with a test Postgres endpoint")
    monkeypatch.setenv("LAKSHYA_CLOUD", "1")
    # Test artifacts use a separate key; synthetic workspaces are removed after each test.
    monkeypatch.setenv(
        "LAKSHYA_STORAGE_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    )
    settings.cookie_secure = False
    settings.embedding_backend = "lexical"
    settings.api_key = SecretStr(secrets.token_urlsafe(48))
    store.initialize()
    app = create_app(settings)
    users = []
    try:
        with TestClient(app) as client:
            yield client, app, users
    finally:
        with store.connection() as db:
            for user in users:
                for table, column in [
                    ("sessions", "user_id"),
                    ("users", "id"),
                    ("cloud_files", "user_id"),
                    ("cloud_commands", "user_id"),
                ]:
                    db.execute(f"DELETE FROM {table} WHERE {column}=%s", (user,))


def signup(client, users):
    account = {
        "name": "Cloud Verification",
        "email": secrets.token_hex(12) + "@example.invalid",
        "password": secrets.token_urlsafe(24),
    }
    response = client.post("/api/auth/signup", json=account)
    assert response.status_code == 201
    users.append(response.json()["id"])
    return account


def test_cloud_account_resume_and_settings_survive_cold_restore(cloud, settings):
    client, app, users = cloud
    account = signup(client, users)
    assert client.get("/api/jobs").json() == []
    assert client.patch("/api/settings", json={"target_roles": ["Data Analyst"]}).status_code == 200
    resume = b"Cloud Verification\ncloud@example.invalid\nSkills\nPython, SQL, Pandas\nProjects\nData analysis | Academic project\nBuilt Python and SQL data analysis.\nEducation\nB.Sc 2025\n"
    assert (
        client.post(
            "/api/profile/import", files={"file": ("resume.txt", resume, "text/plain")}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/settings/credentials", json={"provider": "gemini", "value": "synthetic_test_key"}
        ).status_code
        == 200
    )
    restored = client.get("/api/settings").json()
    assert restored["target_roles"] == ["Data Analyst"]
    assert restored["profile"]["imported"]
    assert restored["credential_status"]["gemini"]
    assert not app.state.accounts.apps
    with store.connection() as db:
        contents = [
            bytes(row["contents"])
            for row in db.execute("SELECT contents FROM cloud_files WHERE user_id=%s", (users[0],))
        ]
    assert not any(
        b"synthetic_test_key" in data or b"Cloud Verification" in data for data in contents
    )
    cookie = client.cookies.get("lakshya_session")
    other = TestClient(create_app(settings))
    other.cookies.set("lakshya_session", cookie)
    assert other.get("/api/auth/me").json()["email"] == account["email"]
    assert client.post("/api/auth/signout").status_code == 200
    assert other.get("/api/auth/me").status_code == 401
    signup(client, users)
    second = client.get("/api/settings").json()
    assert not second["profile"]["imported"]
    assert not second["credential_status"]["gemini"]


def test_cloud_queue_redelivery_and_atomic_outbox(cloud):
    client, app, users = cloud
    signup(client, users)
    response = client.post("/api/runs", json={"stage": "scout", "offline": True, "dry_run": True})
    assert response.status_code == 202
    run_id = response.json()["id"]
    with store.connection() as db:
        row = db.execute(
            "SELECT id FROM cloud_commands WHERE user_id=%s AND NOT done", (users[0],)
        ).fetchone()
    assert row
    process(app.state.accounts, row["id"])
    first = client.get(f"/api/runs/{run_id}").json()
    assert first["status"] == "queued"
    process(app.state.accounts, row["id"])
    second = client.get(f"/api/runs/{run_id}").json()
    assert len(second["agents"]) == len(first["agents"])
    assert client.post("/api/runs", json={"stage": "scout", "dry_run": True}).status_code == 409
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 200
    with store.connection() as db:
        row = db.execute(
            "SELECT id FROM cloud_commands WHERE user_id=%s AND NOT done", (users[0],)
        ).fetchone()
    process(app.state.accounts, row["id"])
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "stopped"


def test_cloud_cache_age_and_reservation_flush_survive_rollback(cloud, settings):
    _, _, users = cloud
    identity = str(uuid4())
    users.append(identity)
    root = settings.data_dir / "accounts" / identity
    with pytest.raises(RuntimeError):
        with store.workspace(identity, root):
            path = root / "source-cache" / "sample.json"
            path.parent.mkdir()
            path.write_text('{"jobs": []}')
            os.utime(path, (1000000, 1000000))
            (root / "reservation.txt").write_text("reserved")
            store.flush(root)
            (root / "reservation.txt").write_text("not persisted")
            raise RuntimeError("worker terminated after a durable reservation")
    with store.workspace(identity, root):
        assert (root / "reservation.txt").read_text() == "reserved"
        assert (root / "source-cache/sample.json").stat().st_mtime == 1000000
        # Refreshing an identical feed must persist its new age without rewriting content.
        os.utime(root / "source-cache/sample.json", (2000000, 2000000))
    with store.workspace(identity, root):
        assert (root / "source-cache/sample.json").stat().st_mtime == 2000000
