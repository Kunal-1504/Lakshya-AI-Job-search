from fastapi.testclient import TestClient
from lakshya.api.app import create_app
from lakshya.db.seed import seed_demo


def test_health_authentication_cors_and_seed_inspection(settings, database):
    with database() as session, session.begin():
        seed_demo(session)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["schema_revision"] == "0001_foundations"
        assert client.get("/api/foundation").status_code == 401
        assert client.get("/api/foundation", headers={"X-API-Key": "wrong"}).status_code == 401
        response = client.get("/api/foundation", headers={"X-API-Key": "test-api-key"})
        assert response.status_code == 200
        assert response.json()["counts"] == {"jobs": 3, "applications": 3, "demo_jobs": 3}
        assert "test-api-key" not in response.text
        assert "X-Request-ID" in response.headers
        preflight = client.options(
            "/api/foundation",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unmigrated_database_has_actionable_health_failure(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert "init-db" in response.json()["detail"]
