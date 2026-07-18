from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.health.dependencies import get_health_service
from app.health.schemas import LivenessResponse, ReadinessResponse
from app.health.service import HealthService

router = APIRouter(prefix="/health", tags=["health"])
HealthServiceDependency = Annotated[HealthService, Depends(get_health_service)]


@router.get("", response_model=LivenessResponse, summary="应用存活检查")
def get_liveness(service: HealthServiceDependency) -> LivenessResponse:
    return service.liveness()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    summary="应用依赖就绪检查",
)
async def get_readiness(
    response: Response,
    service: HealthServiceDependency,
) -> ReadinessResponse:
    readiness = await service.readiness()
    if readiness.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return readiness
