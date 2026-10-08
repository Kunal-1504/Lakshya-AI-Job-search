import asyncio
import time
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lakshya.cloud.app import ReadyCloudApp


@pytest.fixture
def service_key(monkeypatch):
    monkeypatch.setenv("LAKSHYA_SERVICE_KEY", "synthetic-cloud-service-key")
    return {"x-lakshya-service": "synthetic-cloud-service-key"}


def test_container_startup_does_not_wait_for_imports_or_database(service_key):
    calls = []

    @asynccontextmanager
    async def lifespan(app):
        calls.append("inner startup")
        yield
        calls.append("inner shutdown")

    def build():
        calls.append("build")
        app = FastAPI(lifespan=lifespan)

        @app.get("/probe")
        def probe():
            return {"ready": True}

        return app

    with TestClient(ReadyCloudApp(build)) as client:
        assert calls == [], "Uvicorn can bind its port before any cloud initialization"
        assert client.get("/probe").status_code == 401
        assert calls == [], "Unauthenticated requests never initialize private storage"
        assert client.get("/probe", headers=service_key).json() == {"ready": True}
        assert calls == ["build", "inner startup"]
        assert client.get("/probe", headers=service_key).status_code == 200
        assert calls == ["build", "inner startup"]
    assert calls == ["build", "inner startup", "inner shutdown"]


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_complete_initialization(service_key):
    calls = []

    def build():
        time.sleep(0.05)
        calls.append("build")
        app = FastAPI()

        @app.get("/probe")
        def probe():
            return {"ready": True}

        return app

    lazy = ReadyCloudApp(build)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=lazy), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *(client.get("/probe", headers=service_key) for _ in range(8))
        )
    assert all(response.json() == {"ready": True} for response in responses)
    assert calls == ["build"]
    await lazy.context.__aexit__(None, None, None)


def test_failed_initialization_can_retry_without_leaking_private_details(service_key):
    calls = []

    def build():
        calls.append("build")
        if len(calls) == 1:
            raise ConnectionError("private-database-credential-sentinel")
        app = FastAPI()

        @app.get("/probe")
        def probe():
            return {"ready": True}

        return app

    with TestClient(ReadyCloudApp(build)) as client:
        first = client.get("/probe", headers=service_key)
        assert first.status_code == 503 and first.headers["Retry-After"] == "5"
        assert "sentinel" not in first.text
        assert client.get("/probe", headers=service_key).json() == {"ready": True}
    assert len(calls) == 2
