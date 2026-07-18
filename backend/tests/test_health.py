from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from app.core.config import Settings
from app.health.schemas import DependencyCheck, ProbeStatus
from app.main import create_app


@dataclass(frozen=True, slots=True)
class PassingProbe:
    name: str

    async def check(self) -> DependencyCheck:
        return DependencyCheck(name=self.name, status=ProbeStatus.OK)


async def request(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def make_test_settings(**overrides) -> Settings:
    return Settings(_env_file=None, app_env="test", **overrides)


async def test_liveness_returns_service_metadata() -> None:
    app = create_app(settings=make_test_settings())

    response = await request(app, "/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "东软智慧商务 AI 助手平台",
        "environment": "test",
    }


async def test_readiness_is_unavailable_until_required_dependencies_exist() -> None:
    app = create_app(settings=make_test_settings())

    response = await request(app, "/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert {check["name"]: check["status"] for check in response.json()["checks"]} == {
        "database": "pending",
        "redis": "pending",
    }


async def test_readiness_accepts_injected_dependency_probes() -> None:
    probes = (PassingProbe("database"), PassingProbe("redis"))
    app = create_app(settings=make_test_settings(), readiness_probes=probes)

    response = await request(app, "/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": [
            {"name": "database", "status": "ok", "detail": None},
            {"name": "redis", "status": "ok", "detail": None},
        ],
    }
