import time

from fastapi.testclient import TestClient
from lakshya.api.app import create_app

HEADERS = {"X-API-Key": "test-api-key"}


def test_complete_api_review_downloads_stats_export_and_stream(settings, database):
    with TestClient(create_app(settings)) as client:
        run = client.post(
            "/api/runs", headers=HEADERS, json={"demo": True, "dry_run": True}
        ).json()["id"]
        for _ in range(100):
            status = client.get(f"/api/runs/{run}", headers=HEADERS).json()["status"]
            if status in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert status == "completed"
        jobs = client.get("/api/jobs?freshness_hours=24&min_score=65", headers=HEADERS).json()
        assert len(jobs) == 3
        applications = client.get("/api/applications", headers=HEADERS).json()
        identity = applications[0]["id"]
        detail = client.get(f"/api/applications/{identity}", headers=HEADERS).json()
        assert detail["critic_passed"] and detail["tailored_resume"] and detail["master_resume"]
        assert client.get(
            f"/api/applications/{identity}/files/pdf", headers=HEADERS
        ).content.startswith(b"%PDF")
        assert (
            client.post(f"/api/applications/{identity}/approve", headers=HEADERS).status_code == 200
        )
        assert (
            client.patch(
                f"/api/applications/{identity}", headers=HEADERS, json={"status": "applied"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/applications/{identity}/confirm-manual",
                headers=HEADERS,
                json={"confirmed": True},
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/api/applications/{identity}",
                headers=HEADERS,
                json={"notes": "Interview practice", "expected_status": "new"},
            ).status_code
            == 409
        )
        assert (
            client.patch(
                f"/api/applications/{identity}", headers=HEADERS, json={"notes": "My notes"}
            ).status_code
            == 200
        )
        assert client.get("/api/export", headers=HEADERS).content.startswith(b"PK")
        assert client.get("/api/stats", headers=HEADERS).json()["applied"] == 0
        assert "event: agent" in client.get(f"/api/runs/{run}/events", headers=HEADERS).text
        assert client.post("/api/runs", headers=HEADERS, json={"auto": True}).status_code == 422
        assert client.get("/api/jobs").status_code == 401


def test_profile_upload_screening_answers_and_live_onboarding(settings, database):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/runs", headers=HEADERS, json={}).status_code == 409
        text = b"Candidate Name\nSkills\nPython, SQL\nProjects\nBuilt Python project.\nEducation\nB.Tech in Computer Science."
        assert (
            client.post(
                "/api/profile/import",
                headers=HEADERS,
                files={"file": ("resume.txt", text, "text/plain")},
            ).status_code
            == 200
        )
        result = client.get("/api/settings", headers=HEADERS).json()
        assert result["profile"]["imported"]
        assert "test-api-key" not in str(result)
        assert (
            client.put(
                "/api/screening-answers",
                headers=HEADERS,
                json={"question": "Notice period", "answer": "Available immediately"},
            ).status_code
            == 200
        )
        assert len(client.get("/api/screening-answers", headers=HEADERS).json()) == 1
        assert (
            client.post(
                "/api/profile/import",
                headers=HEADERS,
                files={"file": ("resume.exe", text, "text/plain")},
            ).status_code
            == 422
        )
