"""考试试卷 API schemas：生成、改分、换题、响应体。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator
from app.schemas.tag_filter import StrictModel, TagFilter, Score


class ExamPaperGenerateRequest(StrictModel):
    """一键出卷请求；cross_set_dedup 默认开启批次内去重。"""

    template_id: int
    title: Optional[str] = None
    n_sets: int = Field(1, ge=1, le=10)
    cross_set_dedup: bool = True
    scope: TagFilter = Field(default_factory=TagFilter)
    duration_minutes: Optional[int] = None
    seed: Optional[str] = Field(None, max_length=64)


class ExamPaperItemScoreUpdate(BaseModel):
    score: Score


class ExamPaperItemReplaceRequest(BaseModel):
    """换题：random_same_type 同题型随机；manual 指定 question_id。"""

    mode: str = Field(..., pattern="^(random_same_type|manual)$")
    question_id: Optional[int] = None
    filters: Optional[dict[str, Any]] = None
    # True 时允许在存在模板偏离 warnings 的情况下仍完成替换。
    accept_template_deviation: bool = False


class ExamPaperItemOut(BaseModel):
    id: int
    paper_id: int
    question_id: int
    part_key: str
    section_key: str
    q_type: str
    tag_snapshot_json: list[dict[str, Any]]
    seq: int
    score: float
    content_snapshot_json: dict[str, Any]

    model_config = {"from_attributes": True}


class ExamPaperOut(BaseModel):
    id: int
    batch_id: int
    subject_id: int
    title: str
    set_index: int
    status: str
    template_snapshot_json: dict[str, Any]
    actual_total_score: float
    duration_minutes: Optional[int] = None
    instructions: Optional[str] = None
    seed: Optional[str] = None
    finalized_at: Optional[datetime] = None
    created_by: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    items: list[ExamPaperItemOut] = []
    template_warnings: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ExamPaperBatchOut(BaseModel):
    id: int
    subject_id: int
    template_id: int
    n_sets: int
    cross_set_dedup: bool
    scope_json: Optional[Any] = None
    template_snapshot_json: dict[str, Any]
    seed: Optional[str] = None
    created_by: int
    created_at: Optional[datetime] = None
    papers: list[ExamPaperOut] = []

    model_config = {"from_attributes": True}


class ExamPaperExportQuery(BaseModel):
    mode: str = Field(..., pattern="^(with_answers|without_answers)$")
    include_analysis: bool = False
