from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


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
