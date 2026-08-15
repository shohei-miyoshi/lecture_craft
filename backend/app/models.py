from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GuestSessionResponse(BaseModel):
    session_id: str
    experiment_id: Optional[str] = None
    participant_label: Optional[str] = None
    csrf_token: Optional[str] = None
    user: Dict[str, Any] = Field(default_factory=dict)


class AuthCredentialsRequest(BaseModel):
    username: str
    password: str


class GenerateRequest(BaseModel):
    filename: str
    detail: Literal["summary", "standard", "detail"]
    difficulty: Literal["intro", "basic", "advanced"]
    mode: Literal["audio", "video", "hl"]
    request_token: Optional[str] = None
    client_project_id: Optional[str] = None
    interactive_review_enabled: bool = False
    layout_review_enabled: bool = False
    script_review_enabled: bool = False
    generation_conditions: Dict[str, Any] = Field(default_factory=dict)
    generation_run_id: Optional[str] = None
    generation_job_id: Optional[str] = None
    correction_memories: List[Dict[str, Any]] = Field(default_factory=list)


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


class PreviewAudioRequest(BaseModel):
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    scope: Literal["slide", "range", "all"] = "slide"
    slide_idx: Optional[int] = None
    sentences: List[Dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None
    generation_ref: Dict[str, Any] = Field(default_factory=dict)
    settings: ExportSettings = Field(default_factory=ExportSettings)


class ReviewAssignmentRequest(BaseModel):
    slides: List[Dict[str, Any]] = Field(default_factory=list)
    sentences: List[Dict[str, Any]] = Field(default_factory=list)
    highlights: List[Dict[str, Any]] = Field(default_factory=list)
    generation_ref: Dict[str, Any] = Field(default_factory=dict)
    settings: ExportSettings = Field(default_factory=ExportSettings)


class ReviewAssignmentStartRequest(BaseModel):
    run_id: str


class FinalRenderStartRequest(BaseModel):
    project_id: str
    run_id: str
    type: Literal["video", "video_highlight"] = "video_highlight"
    draft_version: Optional[int] = Field(default=None, ge=1)


class ResearchSessionRequest(BaseModel):
    session_id: Optional[str] = None
    trigger: str = "manual"
    mode: Optional[str] = None
    generation_ref: Dict[str, Any] = Field(default_factory=dict)
    operation_logs: List[Dict[str, Any]] = Field(default_factory=list)
    research: Dict[str, Any] = Field(default_factory=dict)
    settings: Dict[str, Any] = Field(default_factory=dict)


class ProjectCreateV2Request(BaseModel):
    name: str
    usage_context: Literal["general", "research"] = "general"


class ProjectDraftPutRequest(BaseModel):
    base_version: int = Field(ge=1)
    name: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class ProjectRevisionRequest(BaseModel):
    revision_kind: Literal[
        "manual_save",
        "generation_completed",
        "layout_confirmed",
        "script_confirmed",
        "assignment_confirmed",
        "rendered",
    ] = "manual_save"


class GenerationRunCreateRequest(BaseModel):
    source_artifact_id: str
    detail: Literal["summary", "standard", "detail"]
    difficulty: Literal["intro", "basic", "advanced"]
    mode: Literal["audio", "video", "hl"]
    usage_context: Literal["general", "research"] = "general"
    layout_review_enabled: bool = False
    script_review_enabled: bool = False


class ReviewStageConfirmRequest(BaseModel):
    run_id: str
    draft_version: int = Field(ge=1)


class RunAnalysisStatusRequest(BaseModel):
    analysis_status: Literal["candidate", "included", "excluded"]


class ProjectEventItem(BaseModel):
    external_event_id: Optional[str] = None
    generation_run_id: Optional[str] = None
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


class GenerationConditionSettings(BaseModel):
    kg_mode: Literal["off", "slide", "global", "global_slide"] = "global_slide"
    log_reuse_enabled: bool = False
    review_flow_enabled: bool = True
    prompt_strategy_version: str = "baseline_v1"


class ExperimentConditionPatchRequest(BaseModel):
    scope_type: Literal["global", "experiment"] = "global"
    scope_key: Optional[str] = None
    generation_conditions: GenerationConditionSettings = Field(default_factory=GenerationConditionSettings)


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


class ResearchJsonlExportRequest(BaseModel):
    experiment_id: Optional[str] = None
    project_id: Optional[str] = None
    run_ids: List[str] = Field(default_factory=list)
    included_only: bool = True
    include_raw_text: bool = True
    purpose: Literal["analysis", "prompt_reuse", "fine_tuning"] = "analysis"
