"""Shared replacement eligibility and immutable source-rule checks."""
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from app.models.exam_paper import ExamPaper,ExamPaperItem
from app.models.question import Question, question_tags
from app.models.tag import Tag
from app.crud.crud_question import is_question_visible
from app.schemas.tag_filter import TagFilter
from app.services.tag_assignment import resolve_tags,template_tag_ids
from .answerable import is_answerable_question
from .snapshot import value

async def forbidden_ids(db,paper,item):
    ids={i.question_id for i in paper.items}
    if paper.batch.cross_set_dedup:
        ids.update((await db.execute(select(ExamPaperItem.question_id).join(ExamPaper)
                   .where(ExamPaper.batch_id==paper.batch_id).with_for_update())).scalars())
    return ids

def eligible(question,*,paper,forbidden,viewer=None):
    return question.subject_id==paper.subject_id and question.id not in forbidden and is_answerable_question(question) and (viewer is None or is_question_visible(question,viewer))

class ReplacementRules:
    def __init__(self,paper):self.paper=paper
    @classmethod
    async def load(cls,db,paper):
        return cls(paper)
    def section(self,item):
        return next((s for p in self.paper.template_snapshot_json["parts"] for s in p["sections"]
                     if p["key"]==item.part_key and s["key"]==item.section_key),None)
    def warnings(self,item=None,question=None):
        warnings=[]
        for row in self.paper.items:
            q=question if item and row.id==item.id else None
            tid=value(q.q_type) if q else row.q_type
            tags={t.id for t in q.tags} if q else {t["id"] for t in row.tag_snapshot_json}
            section=self.section(row)
            if not section: warnings.append(f"第{row.seq}题来源规则不存在");continue
            if tid!=section["q_type"]:warnings.append(f"第{row.seq}题题型偏离模板")
            if not TagFilter.model_validate(section.get("tag_filter",{})).matches(tags):warnings.append(f"第{row.seq}题标签偏离来源规则")
            if not TagFilter.model_validate(self.paper.batch.scope_json or {}).matches(tags):warnings.append(f"第{row.seq}题超出原抽题标签范围")
        return warnings
    async def validate_tags(self,db,item):
        section=self.section(item)
        if not section:raise ValueError("来源规则不存在")
        ids=set(TagFilter.model_validate(section.get("tag_filter",{})).tag_ids)
        ids.update(TagFilter.model_validate(self.paper.batch.scope_json or {}).tag_ids)
        await resolve_tags(db,ids,subject_id=self.paper.subject_id)

async def load_replacement_question(db,question_id):
    question = (await db.execute(select(Question).where(Question.id==question_id).with_for_update()
                                 .execution_options(populate_existing=True))).scalar_one_or_none()
    if question:
        tags = (await db.execute(select(Tag).join(question_tags, question_tags.c.tag_id == Tag.id)
                                .where(question_tags.c.question_id == question.id).order_by(Tag.id)
                                .with_for_update().execution_options(populate_existing=True))).scalars().all()
        set_committed_value(question, 'tags', list(tags))
    return question

def persist_warnings(paper,warnings):
    for row in paper.items:
        row.content_snapshot_json={**row.content_snapshot_json,"_template_warnings":warnings}
