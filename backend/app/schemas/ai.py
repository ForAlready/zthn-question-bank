from enum import Enum
from pydantic import BaseModel, field_validator, model_validator
from typing import List, Optional, Union, Any

class QuestionTypeEnum(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_THE_BLANK = "fill_in_the_blank"
    FREE_RESPONSE = "free_response"

class AIQuestion(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def preserve_type_name(cls, data):
        if isinstance(data, dict):
            data = {**data, "raw_type_name": data.get("raw_type_name") or str(data.get("q_type") or data.get("type") or "")}
        return data
    q_type: Optional[QuestionTypeEnum] = None
    raw_type_name: Optional[str] = None
    tag_ids: Optional[List[int]] = None
    warnings: Optional[List[str]] = None

    @field_validator("q_type",mode="before")
    @classmethod
    def map_type(cls,v):
        from app.services.question_type_names import coerce_q_type
        try:return coerce_q_type(v).value
        except ValueError:return None
    content: str
    options: Optional[List[str]] = None
    # Allow structured answer for fill-in-the-blank (List[List[str]]) or string for others
    answer: Optional[Union[str, List[List[str]], Any]] = None 
    thinking: Optional[str] = None
    analysis: Optional[str] = None
    summary: Optional[str] = None
    difficulty: Optional[int] = None
    knowledge_points: Optional[List[str]] = None
    knowledge_point_ids: Optional[List[int]] = None
    tags: Optional[List[str]] = None


class QuestionList(BaseModel):
    questions: List[AIQuestion]
