"""
Schemas for Phase 3 research run ledger and bundle upload.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ResearchRunBase(BaseModel):
    objective: str = Field(..., min_length=1)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    rank_spec: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(None, max_length=200)
    company_research_run_id: Optional[UUID] = None


class ResearchRunCreate(ResearchRunBase):
    pass


class ResearchRunRead(ResearchRunBase):
    id: UUID
    status: str
    plan_json: Optional[Dict[str, Any]] = None
    bundle_sha256: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResearchRunWithCounts(ResearchRunRead):
    step_counts: Dict[str, int] = Field(default_factory=dict)


class ResearchRunStepRead(BaseModel):
    id: UUID
    run_id: UUID
    step_key: str
    step_type: Optional[str]
    status: str
    inputs_json: Dict[str, Any]
    outputs_json: Dict[str, Any]
    provider_meta: Dict[str, Any]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    output_sha256: Optional[str]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Run Bundle v1
# ---------------------------------------------------------------------------

class RunStepV1(BaseModel):
    step_key: str
    step_type: Literal["search", "fetch", "extract", "validate", "compose", "finalize"]
    status: Literal["queued", "running", "ok", "failed", "skipped"] = "ok"
    inputs_json: Dict[str, Any] = Field(default_factory=dict)
    outputs_json: Dict[str, Any] = Field(default_factory=dict)
    provider_meta: Dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    output_sha256: Optional[str] = None
    error: Optional[str] = None


class SourceV1(BaseModel):
    sha256: str
    url: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    mime_type: Optional[str] = None
    title: Optional[str] = None
    content_text: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    # Optional temp_id for backward compatibility only
    temp_id: Optional[str] = None

    @field_validator("sha256")
    @classmethod
    def validate_sha(cls, v: str):
        if len(v) != 64:
            raise ValueError("sha256 must be 64 hex characters")
        return v.lower()


class RunBundleV1(BaseModel):
    version: Literal["run_bundle_v1"]
    run_id: UUID
    plan_json: Dict[str, Any]
    steps: List[RunStepV1]
    sources: List[SourceV1]
    proposal_json: Dict[str, Any]


class BundleAcceptedResponse(BaseModel):
    run_id: UUID
    bundle_sha256: str
    status: str
    already_accepted: bool = False
    message: Optional[str] = None


class BundleValidationError(BaseModel):
    loc: str
    msg: str


class BundleValidationResponse(BaseModel):
    ok: bool
    errors: List[BundleValidationError] = Field(default_factory=list)

    @classmethod
    def from_errors(cls, errors: List[BundleValidationError]):
        return cls(ok=len(errors) == 0, errors=errors)
