"""Shared flat tag condition; groups never affect matching."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

Score = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", json_encoders={Decimal: float})


class TagFilter(StrictModel):
    tag_ids: list[StrictInt] = Field(default_factory=list)
    match: Literal["any", "all"] = "any"

    @field_validator("tag_ids")
    @classmethod
    def valid_ids(cls, values):
        if any(v <= 0 for v in values):
            raise ValueError("标签 ID 必须为正整数")
        return list(dict.fromkeys(values))

    def matches(self, ids) -> bool:
        selected = set(self.tag_ids)
        return not selected or (selected <= set(ids) if self.match == "all" else bool(selected & set(ids)))
