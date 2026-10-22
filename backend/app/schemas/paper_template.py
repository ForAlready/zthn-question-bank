"""Strict v2 paper template contract."""
from datetime import datetime
from typing import Any, Literal
from pydantic import Field, model_validator
from app.models.question import QuestionType
from app.schemas.tag_filter import StrictModel, TagFilter, Score

class TemplateSection(StrictModel):
    key: str = Field(min_length=1,max_length=64)
    q_type: QuestionType
    tag_filter: TagFilter = Field(default_factory=TagFilter)
    count: int = Field(gt=0)
    score_each: Score

class TemplatePart(StrictModel):
    key: str = Field(min_length=1,max_length=64)
    title: str = Field(min_length=1)
    part_score: Score
    sections: list[TemplateSection] = Field(min_length=1)

class PaperTemplateBase(StrictModel):
    schema_version: Literal[2] = 2
    name: str = Field(min_length=1,max_length=255)
    total_score: Score
    parts: list[TemplatePart] = Field(min_length=1)
    scope: TagFilter = Field(default_factory=TagFilter)
    duration_minutes: int | None = Field(None,gt=0)
    instructions: str | None = None
    enabled: bool = True

class PaperTemplateCreate(PaperTemplateBase):
    subject_id: int = Field(gt=0)

class PaperTemplateUpdate(StrictModel):
    name: str | None = Field(None,min_length=1,max_length=255)
    total_score: Score | None = None
    parts: list[TemplatePart] | None = Field(None,min_length=1)
    scope: TagFilter = Field(default_factory=TagFilter)
    duration_minutes: int | None = Field(None,gt=0)
    instructions: str | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def nonnull_required(self):
        for key in ("name","total_score","parts","enabled"):
            if key in self.model_fields_set and getattr(self,key) is None:
                raise ValueError(f"{key} 不允许为空")
        return self

class PaperTemplateOut(PaperTemplateBase):
    id: int
    subject_id: int
    is_system_default: bool
    seed_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def from_orm(cls,v):
        if hasattr(v,"parts_json"):
            return {**{k:getattr(v,k) for k in ("id","subject_id","schema_version","name","total_score","duration_minutes","instructions","enabled","is_system_default","seed_key","created_at","updated_at")},
                    "parts":v.parts_json,"scope":v.scope_json or {}}
        return v
