from fastapi import Request

from app.health.service import HealthService


def get_health_service(request: Request) -> HealthService:
    return HealthService(
        settings=request.app.state.settings,
        probes=request.app.state.readiness_probes,
    )
