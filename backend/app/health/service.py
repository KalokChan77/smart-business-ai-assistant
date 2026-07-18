import asyncio
from collections.abc import Sequence

from app.core.config import Settings
from app.health.probes import ReadinessProbe
from app.health.schemas import LivenessResponse, ProbeStatus, ReadinessResponse


class HealthService:
    def __init__(self, settings: Settings, probes: Sequence[ReadinessProbe]) -> None:
        self._settings = settings
        self._probes = tuple(probes)

    def liveness(self) -> LivenessResponse:
        return LivenessResponse(
            service=self._settings.app_name,
            environment=self._settings.app_env,
        )

    async def readiness(self) -> ReadinessResponse:
        checks = list(await asyncio.gather(*(probe.check() for probe in self._probes)))
        is_ready = all(check.status == ProbeStatus.OK for check in checks)
        return ReadinessResponse(
            status="ready" if is_ready else "not_ready",
            checks=checks,
        )
