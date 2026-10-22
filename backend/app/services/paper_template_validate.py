"""Strict template arithmetic and stable rule identifiers."""
from decimal import Decimal
from pydantic import ValidationError
from app.schemas.paper_template import TemplatePart

class TemplateValidationError(ValueError):
    def __init__(self,message,*,errors=None):
        super().__init__(message);self.message=message;self.errors=errors or [message]

def validate_template_structure(*,total_score,parts):
    try:
        parts=[p if isinstance(p,TemplatePart) else TemplatePart.model_validate(p) for p in parts]
    except (ValidationError,ValueError) as e: raise TemplateValidationError(str(e)) from e
    if not parts: raise TemplateValidationError("模板至少需要一个分区")
    pkeys=set();skeys=set();total=Decimal(0)
    for p in parts:
        if p.key in pkeys: raise TemplateValidationError("分区 key 重复")
        pkeys.add(p.key)
        score=sum((s.count*s.score_each for s in p.sections),Decimal(0))
        if score!=p.part_score: raise TemplateValidationError(f"【{p.title}】规则小计不等于分区总分")
        for s in p.sections:
            if s.key in skeys: raise TemplateValidationError("规则 key 必须在模板内唯一")
            skeys.add(s.key)
        total+=score
    if total!=Decimal(str(total_score)): raise TemplateValidationError("分区总分合计不等于模板目标总分")
    return parts

def parts_to_json(parts):
    return [(p if isinstance(p,TemplatePart) else TemplatePart.model_validate(p)).model_dump(mode="json") for p in parts]
