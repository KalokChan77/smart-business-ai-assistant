from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DifyIndexingStatus = Literal[
    "waiting",
    "parsing",
    "cleaning",
    "splitting",
    "indexing",
    "completed",
    "error",
    "paused",
    "stopped",
]


class DifyDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    name: str | None = None


class DifySegmentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str
    document: DifyDocumentPayload | None = None


class DifyRetrievalRecordPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    score: float | None = Field(default=None, allow_inf_nan=False)
    segment: DifySegmentPayload


class DifyRetrieveResponsePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    records: list[DifyRetrievalRecordPayload]


class DifyDocumentMutationDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    indexing_status: DifyIndexingStatus


class DifyDocumentMutationResponsePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document: DifyDocumentMutationDocumentPayload
    batch: str = Field(min_length=1, max_length=128)


class DifyDocumentIndexingStatusPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    indexing_status: DifyIndexingStatus
    error: str | None = None
    completed_segments: int | None = Field(default=None, ge=0)
    total_segments: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_progress(self) -> "DifyDocumentIndexingStatusPayload":
        if (
            self.completed_segments is not None
            and self.total_segments is not None
            and self.completed_segments > self.total_segments
        ):
            raise ValueError("completed_segments exceeds total_segments")
        return self


class DifyDocumentIndexingStatusResponsePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[DifyDocumentIndexingStatusPayload]


@dataclass(frozen=True, slots=True)
class DifyRetrievalRecord:
    document_id: str
    document_name: str
    content: str
    score: float | None


@dataclass(frozen=True, slots=True)
class DifyDocumentMutationResult:
    document_id: str
    indexing_status: DifyIndexingStatus
    batch: str


@dataclass(frozen=True, slots=True)
class DifyDocumentIndexingStatus:
    document_id: str
    indexing_status: DifyIndexingStatus
    error_present: bool
    completed_segments: int | None
    total_segments: int | None
