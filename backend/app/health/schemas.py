from enum import StrEnum

from pydantic import BaseModel


class ProbeStatus(StrEnum):
    OK = "ok"
    PENDING = "pending"
    ERROR = "error"


class DependencyCheck(BaseModel):
    name: str
    status: ProbeStatus
    detail: str | None = None


class LivenessResponse(BaseModel):
    status: str = "ok"
    service: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    checks: list[DependencyCheck]
