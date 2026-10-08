import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from lakshya.api.app import create_app
from lakshya.config import ModelPrice
from lakshya.db.base import utc_now
from lakshya.db.models import AgentRun, BudgetReservation, JobRecord, PipelineRun
from lakshya.llm import LLM, ProviderUnavailable
from lakshya.matcher import role_allowed
from lakshya.models import Job
from lakshya.pipeline import Pipeline
from lakshya.scrapers.registry import REGISTRY
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select

HEADERS = {"X-API-Key": "test-api-key"}


class PublicSource:
    calls = 0

    def __init__(self, settings, http):
        pass

    async def collect(self):
        PublicSource.calls += 1
        return [
            Job(
                id="himalayas:public-one",
                title="Junior AI Engineer",
                company="Test Employer",
                location="India",
                remote_type="remote",
                description="Python SQL. 0-1 years experience.",
                apply_url="https://example.invalid/real-test-job",
                posted_at=utc_now(),
                source="himalayas",
            )
        ]


def wait_for_run(client, identity):
    for _ in range(100):
        run = client.get(f"/api/runs/{identity}", headers=HEADERS).json()
        if run["status"] in {"completed", "failed"}:
            return run
        time.sleep(0.05)
    raise AssertionError("Run did not complete")


def test_real_discovery_needs_no_resume_or_llm_key_and_uses_cache(settings, database, monkeypatch):
    PublicSource.calls = 0
    monkeypatch.setitem(REGISTRY, "himalayas", PublicSource)
    settings.enabled_sources = ["himalayas"]
    with TestClient(create_app(settings)) as client:
        for _ in range(2):
            for _attempt in range(20):
                response = client.post("/api/runs", headers=HEADERS, json={"stage": "scout"})
                if response.status_code != 409:
                    break
                time.sleep(0.05)
            assert response.status_code == 202
            assert wait_for_run(client, response.json()["id"])["status"] == "completed"
        jobs = client.get("/api/jobs", headers=HEADERS).json()
        assert len(jobs) == 1 and not jobs[0]["is_demo"]
        assert PublicSource.calls == 1
        assert not (settings.data_dir / "master_profile.json").exists()
        assert not (settings.data_dir / "demo_master_profile.json").exists()
        live = client.get("/api/live", headers=HEADERS).json()
        assert live["discovery_ready"] and not live["ai_pipeline_ready"]
        assert any(item["id"] == "resume" for item in live["requirements"])


def test_scheduler_starts_real_discovery_and_production_rejects_demo(
    settings, database, monkeypatch
):
    monkeypatch.setitem(REGISTRY, "himalayas", PublicSource)
    settings.enabled_sources = ["himalayas"]
    app = create_app(settings)
    manager = app.state.run_manager
    settings.live_search_enabled = True
    manager.scheduled_search()
    first = manager.last_scheduled_run
    manager.scheduled_search()
    assert first and first == manager.last_scheduled_run
    manager.close()
    with database() as session:
        run = session.get(PipelineRun, first)
        assert run.trigger == "scheduled" and not run.options["demo"]
        assert run.options["stage"] == "scout" and run.status == "completed"
    settings.environment = "production"
    settings.live_search_enabled = False
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/runs", headers=HEADERS, json={"demo": True}).status_code == 422
    with database() as session:
        assert all(not job.is_demo for job in session.scalars(select(JobRecord)))


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: bool


def gemini_agent(settings, database):
    settings.ai_provider = "gemini"
    settings.gemini_api_key = SecretStr("private-test-key")
    settings.agent_models = {"jd_analyst": "gemini-3.8-flash"}
    settings.model_prices_per_million = {
        "gemini-3.8-flash": ModelPrice(input_usd=0.75, output_usd=3.75)
    }
    settings.llm_request_interval_seconds = 0
    pipeline = Pipeline(settings)
    identity = pipeline.start({"dry_run": True})
    with database() as session, session.begin():
        row = AgentRun(run_id=identity, agent_name="jd_analyst")
        session.add(row)
        session.flush()
        agent = row.id
    return pipeline, identity, agent


def test_gemini_schema_header_and_actual_usage(settings, database, monkeypatch):
    pipeline, identity, agent = gemini_agent(settings, database)
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "private-test-key"
        assert (
            "private-test-key" not in str(request.url)
            and "private-test-key" not in request.content.decode()
        )
        assert body["generationConfig"]["responseJsonSchema"]["required"] == ["ready"]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": '{"ready":true}'}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 25,
                    "candidatesTokenCount": 7,
                    "thoughtsTokenCount": 3,
                },
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        "lakshya.llm.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    try:
        assert (
            LLM(settings, pipeline.engine, identity, agent, "jd_analyst")
            .structured("Connectivity check", {}, Reply)
            .ready
        )
        with database() as session:
            reservation = session.scalar(select(BudgetReservation))
            assert reservation.actual_tokens == 35 and reservation.actual_cost_usd == 0
            assert session.get(AgentRun, agent).output_tokens == 10
        assert len(requests) == 1
    finally:
        pipeline.close()


def test_gemini_quota_failure_retains_reservation_without_retry(settings, database, monkeypatch):
    pipeline, identity, agent = gemini_agent(settings, database)
    original_client = httpx.Client
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})

    monkeypatch.setattr(
        "lakshya.llm.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    try:
        with pytest.raises(ProviderUnavailable, match="quota reached"):
            LLM(settings, pipeline.engine, identity, agent, "jd_analyst").structured(
                "Check", {}, Reply
            )
        with database() as session:
            assert session.scalar(select(BudgetReservation)).state == "reserved"
        assert len(calls) == 1
    finally:
        pipeline.close()


def test_role_meaning_does_not_confuse_adjacent_jobs(settings):
    def listing(title, description="Python SQL"):
        return Job(
            id="test",
            source="test",
            company="Test",
            title=title,
            location="Pune",
            description=description,
            apply_url="https://example.invalid/test",
        )

    assert not role_allowed(listing("Design Engineer", "AI infrastructure"), settings)
    assert not role_allowed(listing("Data Engineer"), settings)
    assert not role_allowed(listing("DevOps Engineer"), settings)
    assert role_allowed(listing("Backend Software Engineer - AI Finance Agent"), settings)
    assert role_allowed(listing("Junior Machine Learning Engineer"), settings)
