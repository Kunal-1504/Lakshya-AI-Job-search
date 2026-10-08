from fastapi.testclient import TestClient
from lakshya.api.app import create_app

PASSWORD = "private-test-password-123"


def test_signup_session_logout_and_password_protection(settings, database):
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/auth/me").status_code == 401
        result = client.post(
            "/api/auth/signup",
            json={"name": "Candidate", "email": "one@example.invalid", "password": PASSWORD},
        )
        assert result.status_code == 201
        assert "password" not in result.text
        assert "httponly" in result.headers["set-cookie"].lower()
        assert "samesite=lax" in result.headers["set-cookie"].lower()
        assert client.get("/api/auth/me").json()["name"] == "Candidate"
        assert client.get("/api/settings").status_code == 200
        token = client.cookies.get("lakshya_session")
        with app.state.accounts.db() as db:
            stored = db.execute("SELECT password_hash FROM users").fetchone()[0]
            assert PASSWORD not in stored and stored.startswith("scrypt$")
            assert token not in db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        client.post("/api/auth/signout")
        assert client.get("/api/settings").status_code == 401
        client.cookies.set("lakshya_session", token)
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.clear()
        assert (
            client.post(
                "/api/auth/signin", json={"email": "ONE@example.invalid", "password": PASSWORD}
            ).status_code
            == 200
        )
        assert client.get("/api/settings").status_code == 200


def test_accounts_isolate_resumes_settings_answers_and_job_ids(settings, database):
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/auth/signup",
            json={"name": "First", "email": "first@example.invalid", "password": PASSWORD},
        )
        client.put(
            "/api/screening-answers", json={"question": "Notice period", "answer": "One month"}
        )
        assert (
            client.patch(
                "/api/settings",
                json={
                    "target_roles": ["Data Analyst"],
                    "application_mode": "auto",
                    "daily_application_cap": 3,
                    "max_applications_per_run": 3,
                },
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/profile/import",
                files={
                    "file": (
                        "resume.txt",
                        b"First Candidate\nSkills\nPython, SQL\nProjects\nBuilt a Python dashboard.\nEducation\nB.Tech 2025",
                        "text/plain",
                    )
                },
            ).status_code
            == 200
        )
        client.post("/api/auth/signout")
        client.post(
            "/api/auth/signup",
            json={"name": "Second", "email": "second@example.invalid", "password": PASSWORD},
        )
        preferences = client.get("/api/settings").json()
        assert not preferences["profile"]["imported"]
        assert preferences["application_mode"] == "assist"
        assert client.get("/api/screening-answers").json() == []
        assert client.get("/api/jobs").json() == []
        assert client.get("/api/applications/private-other-account").status_code == 404
        client.post("/api/auth/signout")
        client.post(
            "/api/auth/signin", json={"email": "first@example.invalid", "password": PASSWORD}
        )
        assert client.get("/api/settings").json()["target_roles"] == ["Data Analyst"]
        assert client.get("/api/settings").json()["profile"]["imported"]
        assert client.get("/api/screening-answers").json()[0]["answer"] == "One month"


def test_password_validation_rate_limit_and_cross_site_protection(settings, database):
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/auth/signup", json={"name": "User", "email": "bad", "password": "short"}
            ).status_code
            == 422
        )
        body = {"name": "User", "email": "one@example.invalid", "password": PASSWORD}
        assert (
            client.post(
                "/api/auth/signup", json=body, headers={"Origin": "https://attacker.invalid"}
            ).status_code
            == 403
        )
        assert client.post("/api/auth/signup", json=body).status_code == 201
        assert (
            client.patch(
                "/api/settings",
                json={"application_mode": "auto"},
                headers={"Origin": "https://attacker.invalid"},
            ).status_code
            == 403
        )
        assert client.get("/api/settings").json()["application_mode"] == "assist"
        client.post("/api/auth/signout")
        for _ in range(9):
            client.post(
                "/api/auth/signin", json={"email": body["email"], "password": "incorrect-password"}
            )
        assert client.post("/api/auth/signin", json=body).status_code == 429


def test_credentials_do_not_cross_accounts_or_mutate_process(settings, database, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "operator-private-test-key")
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/auth/signup",
            json={"name": "One", "email": "one@example.invalid", "password": PASSWORD},
        )
        assert not client.get("/api/settings").json()["credential_status"]["gemini"]
        assert (
            client.post(
                "/api/settings/credentials",
                json={"provider": "gemini", "value": "account-one-private-key"},
            ).status_code
            == 200
        )
        assert client.get("/api/settings").json()["credential_status"]["gemini"]
        import os

        assert os.environ["GEMINI_API_KEY"] == "operator-private-test-key"
        client.post("/api/auth/signout")
        client.post(
            "/api/auth/signup",
            json={"name": "Two", "email": "two@example.invalid", "password": PASSWORD},
        )
        assert not client.get("/api/settings").json()["credential_status"]["gemini"]
        assert "account-one-private-key" not in client.get("/api/settings").text


def test_restart_restores_account_preferences_scheduler_credentials_and_session_expiry(
    settings, database, monkeypatch
):
    import time

    from lakshya.api.routes import RunManager

    monkeypatch.setattr(RunManager, "scheduled_search", lambda self: None)
    settings.cookie_secure = True
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as client:
        result = client.post(
            "/api/auth/signup",
            json={
                "name": "Persistent",
                "email": "persistent@example.invalid",
                "password": PASSWORD,
            },
        )
        assert "secure" in result.headers["set-cookie"].lower()
        identity = result.json()["id"]
        client.patch(
            "/api/settings",
            json={
                "target_roles": ["Data Analyst"],
                "live_search_enabled": True,
            },
        )
        client.post(
            "/api/settings/credentials",
            json={
                "provider": "gemini",
                "value": "private-account-test-key",
            },
        )
        token = client.cookies.get("lakshya_session")
    restarted = create_app(settings)
    with TestClient(restarted, base_url="https://testserver") as client:
        assert identity in restarted.state.accounts.apps
        client.cookies.set("lakshya_session", token)
        saved = client.get("/api/settings").json()
        assert saved["target_roles"] == ["Data Analyst"]
        assert saved["live_search_enabled"]
        assert saved["credential_status"]["gemini"]
        with restarted.state.accounts.db() as db:
            db.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/api/settings").status_code == 401
