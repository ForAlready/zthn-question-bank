from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Annotated
from typing import List, Optional

class TagBase(BaseModel):
    name: str = Field(min_length=1,max_length=50)
    enabled: bool = True
    category_id: Optional[int] = None # NULL = 未分类
    color: Optional[str] = "#grey"

    @field_validator("name",mode="before")
    @classmethod
    def trim_name(cls,v):
        if isinstance(v,str): return v.strip()
        return v

class TagCreate(TagBase):
    subject_id: int

class TagUpdate(TagBase):
    enabled: Optional[bool] = None
    name: Optional[Annotated[str, Field(min_length=1, max_length=50)]] = None
    category_id: Optional[int] = None

    @model_validator(mode="after")
    def reject_null_values(self):
        if any(key in self.model_fields_set and getattr(self, key) is None for key in ("name", "enabled")):
            raise ValueError("标签名称和启用状态不能为 null")
        return self

class Tag(TagBase):
    id: int
    subject_id: int

    class Config:
        from_attributes = True


class TagPage(BaseModel):
    items: List[Tag]
    total: int
    page: int
    size: int
    pages: int


class TagImportRowError(BaseModel):
    row: int
    message: str


class TagImportResult(BaseModel):
    status: str  # "success" | "failed"
    created: int
    failed: int
    skipped: int  # duplicate names skipped (not treated as errors)
    total: int
    errors: List[TagImportRowError]
