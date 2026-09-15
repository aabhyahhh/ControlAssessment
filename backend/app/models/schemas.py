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


class AdequacyDocSummary(BaseModel):
    control_id: str | None = None
    doc_kind: str
    filename: str
    period_month: str | None = None
    parsed_step_count: int = 0


class AdequacyUploadResponse(BaseModel):
    documents: list[AdequacyDocSummary]
    total_files_saved: int
    unmatched_control_ids: list[str] = Field(default_factory=list)


class DeclaredEvidenceItem(BaseModel):
    name: str = Field(min_length=1)
    note: str | None = None


class DeclaredEvidenceRequest(BaseModel):
    control_id: str = Field(min_length=1)
    items: list[DeclaredEvidenceItem] = Field(default_factory=list)


class DeclaredEvidenceResponse(BaseModel):
    control_id: str
    items: list[DeclaredEvidenceItem] = Field(default_factory=list)
    updated_at: datetime | None = None


class JustificationEmailItemRequest(BaseModel):
    control_id: str = Field(min_length=1)
    field: str | None = None
    mismatch_description: str = Field(min_length=1)


class SendJustificationEmailRequest(BaseModel):
    recipient_email: EmailStr
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    items: list[JustificationEmailItemRequest] = Field(min_length=1)


class JustificationEmailItemResponse(BaseModel):
    id: str
    control_id: str
    field: str | None = None
    mismatch_description: str
    response_text: str | None = None
    response_attachment_name: str | None = None
    response_uploaded_at: datetime | None = None
    analysis_verdict: str | None = None
    analysis_reasoning: str | None = None
    analyzed_at: datetime | None = None


class JustificationEmailResponse(BaseModel):
    id: str
    recipient_email: str
    subject: str
    sent_at: datetime
    send_status: str
    error_message: str | None = None
    items: list[JustificationEmailItemResponse] = Field(default_factory=list)


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


class RunAllResponse(BaseModel):
    completed_phases: list[int]
    stopped_at_phase: int | None = None
    blocked_reason: str | None = None
    message: str
