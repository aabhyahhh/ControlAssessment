from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None
    created_at: datetime


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    framework: str = "generic"
    audit_period_start: date
    audit_period_end: date


class ProjectResponse(BaseModel):
    id: str
    name: str
    framework: str
    audit_period_start: date
    audit_period_end: date
    current_phase: int
    phase_status: dict
    status: str
    created_at: datetime
    updated_at: datetime


class RcmUploadResponse(BaseModel):
    rcm_upload_id: str
    row_count: int
    column_map: dict
    passthrough: list[str]
    still_missing: list[str]
    header_row_index: int


class ControlResponse(BaseModel):
    id: str
    control_id: str
    control_description: str | None = None
    risk_description: str | None = None
    risk_level: str | None = None
    control_type: str | None = None
    control_nature: str | None = None
    control_frequency: str | None = None
    control_owner: str | None = None
    process: str | None = None
    raw_row: dict = Field(default_factory=dict)


class PhaseResultResponse(BaseModel):
    phase: int
    status: str
    result: dict
    approved_at: datetime | None = None
    updated_at: datetime


class ApprovePhaseRequest(BaseModel):
    phase: int


class EvidenceFolderControlSummary(BaseModel):
    control_id: str
    detected_mode: str
    sample_count: int
    file_count: int


class EvidenceUploadResponse(BaseModel):
    controls: list[EvidenceFolderControlSummary]
    total_files_saved: int
    unmatched_control_ids: list[str]


class SopUploadResponse(BaseModel):
    sop_upload_id: str
    filename: str
    parsed_step_count: int


class AttributeItem(BaseModel):
    id: str
    name: str
    description: str


class SampleColumnItem(BaseModel):
    key: str
    header: str


class ControlAttributesResponse(BaseModel):
    control_id: str
    worksteps: list[str] = Field(default_factory=list)
    attributes: list[AttributeItem] = Field(default_factory=list)
    sample_columns: list[SampleColumnItem] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    status: str
    updated_at: datetime


class ModifyAttributeRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddAttributeRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    position: int | None = None


class ArtifactResponse(BaseModel):
    id: str
    project_id: str
    phase: int | None = None
    filename: str
    artifact_type: str | None = None
    created_at: datetime


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    # camelCase on the wire to match the frontend's ChatMessage type.
    createdAt: datetime


class OverrideResultResponse(BaseModel):
    controls_updated: int
    fields_updated: int
    unknown_control_ids: list[str] = Field(default_factory=list)
    message: str


class RiskBandInput(BaseModel):
    threshold: int
    label: str


class RiskWeightingRequest(BaseModel):
    """use_default=True applies the standard Low=1/Medium=3/High=6 model;
    otherwise score_map and bands must both be supplied."""

    use_default: bool = True
    score_map: dict[str, int] | None = None
    bands: list[RiskBandInput] | None = None


class RunAllResponse(BaseModel):
    completed_phases: list[int]
    stopped_at_phase: int | None = None
    blocked_reason: str | None = None
    message: str
