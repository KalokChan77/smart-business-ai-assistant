from dataclasses import dataclass
from typing import Protocol

from app.health.schemas import DependencyCheck, ProbeStatus


class ReadinessProbe(Protocol):
    @property
    def name(self) -> str: ...

    async def check(self) -> DependencyCheck: ...


@dataclass(frozen=True, slots=True)
class PendingProbe:
    name: str
    detail: str

    async def check(self) -> DependencyCheck:
        return DependencyCheck(
            name=self.name,
            status=ProbeStatus.PENDING,
            detail=self.detail,
        )
