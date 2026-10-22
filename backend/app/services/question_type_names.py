"""Shared fixed-type names for template parsing, AI extraction and import save."""
from enum import Enum
from typing import Any, Mapping

from app.models.question import QuestionType


_ALIASES = {
    **dict.fromkeys(("单选", "单选题", "单项选择", "单项选择题"), "single_choice"),
    **dict.fromkeys(("多选", "多选题", "多项选择", "多项选择题"), "multiple_choice"),
    **dict.fromkeys(("判断", "判断题", "是非", "是非题"), "true_false"),
    **dict.fromkeys(("填空", "填空题"), "fill_in_the_blank"),
    **dict.fromkeys(("问答", "问答题", "解答", "解答题", "简答", "简答题", "论述", "论述题",
                     "案例分析", "案例分析题", "主观", "主观题", "essay", "short_answer"), "free_response"),
}


def coerce_q_type(raw: Any) -> QuestionType:
    if isinstance(raw, QuestionType):
        return raw
    if isinstance(raw, Enum):
        raw = raw.value
    key = str(raw or "").strip().lower()
    try:
        return QuestionType(_ALIASES.get(key, key))
    except ValueError as exc:
        raise ValueError("无法确定题型，请从五种题型中复核选择") from exc


def resolve_import_q_type(raw: Mapping[str, Any]) -> QuestionType:
    """Recover a known original name only when the extracted type is missing.

    An explicit unsupported type still requires review; it is never inferred
    from an answer or replaced with single choice.
    """
    candidate = raw.get("q_type")
    if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
        candidate = raw.get("type") or raw.get("raw_type_name")
    return coerce_q_type(candidate)
