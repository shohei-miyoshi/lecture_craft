from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GuestSessionResponse(BaseModel):
    session_token: str
    session_id: str
    user: Dict[str, Any] = Field(default_factory=dict)


class AuthCredentialsRequest(BaseModel):
    username: str
    password: str


class GenerateRequest(BaseModel):
    pdf_base64: str
    filename: str
    detail: Literal["summary", "standard", "detail"]
    difficulty: Literal["intro", "basic", "advanced"]
    mode: Literal["audio", "video", "hl"]
    request_token: Optional[str] = None


class ExportSettings(BaseModel):
    detail: Optional[Literal["summary", "standard", "detail"]] = "standard"
    difficulty: Optional[Literal["intro", "basic", "advanced"]] = "basic"
    preview_mode: Optional[str] = None
    play_speed: Optional[float] = None


class ExportRequest(BaseModel):
    type: Literal["video_highlight", "video", "audio"]
    mode: Optional[Literal["audio", "video", "hl"]] = "hl"
    slides: List[Dict[str, Any]] = Field(default_factory=list)
    sentences: List[Dict[str, Any]] = Field(default_factory=list)
    highlights: List[Dict[str, Any]] = Field(default_factory=list)
    operation_logs: List[Dict[str, Any]] = Field(default_factory=list)
    research: Dict[str, Any] = Field(default_factory=dict)
    generation_ref: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    source_cache_key: Optional[str] = None
    source_material_name: Optional[str] = None
    source_output_root_name: Optional[str] = None
    settings: ExportSettings = Field(default_factory=ExportSettings)


class ResearchSessionRequest(BaseModel):
    session_id: Optional[str] = None
    trigger: str = "manual"
    mode: Optional[str] = None
    generation_ref: Dict[str, Any] = Field(default_factory=dict)
    operation_logs: List[Dict[str, Any]] = Field(default_factory=list)
    research: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceDraftRequest(BaseModel):
    workspace_id: Optional[str] = None
    revision: Optional[int] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class ProjectUpsertRequest(BaseModel):
    client_project_id: Optional[str] = None
    name: str
    data: Dict[str, Any] = Field(default_factory=dict)


class ProjectPatchRequest(BaseModel):
    name: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class ProjectEventItem(BaseModel):
    external_event_id: Optional[str] = None
    action_type: str
    slide_idx: Optional[int] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    source: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class ProjectEventsRequest(BaseModel):
    events: List[ProjectEventItem] = Field(default_factory=list)


class ExperimentJoinRequest(BaseModel):
    invite_code: str


class ReviewSettingsPatchRequest(BaseModel):
    scope_type: Literal["global", "experiment"] = "global"
    scope_key: Optional[str] = None
    layout_review_mode: Literal["off", "human", "ai", "ai_then_human"]
    script_review_mode: Literal["off", "human"]


class LayoutReviewRecord(BaseModel):
    slide_idx: Optional[int] = None
    highlight_id: Optional[str] = None
    review_source: Literal["human", "ai"] = "human"
    decision: Literal["accepted", "modified", "removed", "added"] = "accepted"
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


class LayoutReviewRequest(BaseModel):
    records: List[LayoutReviewRecord] = Field(default_factory=list)


class ScriptReviewRecord(BaseModel):
    slide_idx: Optional[int] = None
    sentence_id: Optional[str] = None
    review_step: Literal["script_review"] = "script_review"
    before_text: Optional[str] = None
    after_text: Optional[str] = None
    changed_fields: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class ScriptReviewRequest(BaseModel):
    records: List[ScriptReviewRecord] = Field(default_factory=list)
