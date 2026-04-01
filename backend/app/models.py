from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    pdf_base64: str
    filename: str
    detail: Literal["summary", "standard", "detail"]
    difficulty: Literal["intro", "basic", "advanced"]
    mode: Literal["audio", "video", "hl"]


class ExportSettings(BaseModel):
    detail: Optional[Literal["summary", "standard", "detail"]] = "standard"
    difficulty: Optional[Literal["intro", "basic", "advanced"]] = "basic"


class ExportRequest(BaseModel):
    type: Literal["video_highlight", "video", "audio"]
    mode: Optional[Literal["audio", "video", "hl"]] = "hl"
    slides: List[Dict[str, Any]] = Field(default_factory=list)
    sentences: List[Dict[str, Any]] = Field(default_factory=list)
    highlights: List[Dict[str, Any]] = Field(default_factory=list)
    settings: ExportSettings = Field(default_factory=ExportSettings)
