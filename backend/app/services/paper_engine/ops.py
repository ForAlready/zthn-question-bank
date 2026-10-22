"""Serialized paper edits; rule identity is independent of sequence numbers."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
import random
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from app.models.exam_paper import ExamPaper,ExamPaperItem,ExamPaperBatch
from app.models.question import Question
from app.schemas.tag_filter import TagFilter
from .generate import PaperEngineError,prepare,verify_selected
from .answerable import is_answerable_payload
from .snapshot import build_content_snapshot,build_tag_snapshot,order_items,value
from .replacement import ReplacementRules,forbidden_ids,eligible,load_replacement_question,persist_warnings

async def _load_paper(db,paper_id,*,lock=False):
    bid=(await db.execute(select(ExamPaper.batch_id).where(ExamPaper.id==paper_id))).scalar_one_or_none()
    if bid is None:raise PaperEngineError("试卷不存在",status=404)
    if lock:
        await db.execute(select(ExamPaperBatch).where(ExamPaperBatch.id==bid).with_for_update())
    stmt=select(ExamPaper).options(selectinload(ExamPaper.items),selectinload(ExamPaper.batch)).where(ExamPaper.id==paper_id)
    if lock:stmt=stmt.with_for_update().execution_options(populate_existing=True)
    paper = (await db.execute(stmt)).scalar_one()
    if lock:
        # The lookup above can establish an older REPEATABLE READ snapshot while
        # another edit owns the batch lock. Read item state with current locks.
        items = (await db.execute(select(ExamPaperItem).where(ExamPaperItem.paper_id == paper_id)
                                  .order_by(ExamPaperItem.seq).with_for_update()
                                  .execution_options(populate_existing=True))).scalars().all()
        set_committed_value(paper, 'items', list(items))
    return paper

def ensure_draft(paper):
    if paper.status=="final":raise PaperEngineError("试卷已定稿，无法修改",code="paper_finalized",status=409)

async def update_item_score(db,*,paper_id,item_id,score):
    paper=await _load_paper(db,paper_id,lock=True);ensure_draft(paper)
    item=next((i for i in paper.items if i.id==item_id),None)
    if not item:raise PaperEngineError("题位不存在",status=404)
    score=Decimal(str(score))
    if score<=0 or not score.is_finite() or score.as_tuple().exponent < -1:raise PaperEngineError("分值必须为正数，最多一位小数")
    item.score=score;paper.actual_total_score=sum((i.score for i in paper.items),Decimal(0))
    await db.commit();return await _load_paper(db,paper_id)

async def finalize_paper(db,*,paper_id,user_id):
    paper=await _load_paper(db,paper_id,lock=True)
    if paper.status=="final":return paper
    ids=[i.question_id for i in paper.items]
    if len(ids)!=len(set(ids)) or not ids:raise PaperEngineError("试卷存在重复或缺失题目")
    if not all(is_answerable_payload(i.content_snapshot_json.get("answer")) for i in paper.items):raise PaperEngineError("试卷快照答案不完整")
    paper.status="final";paper.finalized_by=user_id;paper.finalized_at=datetime.utcnow()
    await db.commit();return await _load_paper(db,paper_id)

async def replace_item(db,*,paper_id,item_id,mode,question_id=None,filters=None,viewer=None,accept_template_deviation=False):
    paper=await _load_paper(db,paper_id,lock=True);ensure_draft(paper)
    item=next((i for i in paper.items if i.id==item_id),None)
    if not item:raise PaperEngineError("题位不存在",status=404)
    rules=await ReplacementRules.load(db,paper)
    forbidden=await forbidden_ids(db,paper,item)
    if mode=="random_same_type":
        try:await rules.validate_tags(db,item)
        except ValueError as exc:raise PaperEngineError(str(exc)) from exc
        section=rules.section(item)
        rows=(await db.execute(select(Question).options(selectinload(Question.tags))
              .where(Question.subject_id==paper.subject_id,Question.q_type==section['q_type']))).scalars().all()
        scope=TagFilter.model_validate(paper.batch.scope_json or {})
        condition=TagFilter.model_validate(section["tag_filter"])
        rows=[q for q in rows if eligible(q,paper=paper,forbidden=forbidden,viewer=viewer)
              and scope.matches(t.id for t in q.tags) and condition.matches(t.id for t in q.tags)]
        if not rows:raise PaperEngineError("没有满足当前题型、标签、范围和去重条件的其他题目")
        chosen=await load_replacement_question(db,random.choice(rows).id)
    elif mode=="manual":
        chosen=await load_replacement_question(db,question_id)
    else:raise PaperEngineError("不支持的换题方式")
    if not chosen or not eligible(chosen,paper=paper,forbidden=forbidden,viewer=viewer):raise PaperEngineError("所选题目不可用或已被使用")
    warnings=rules.warnings(item,chosen)
    if warnings and mode=="manual" and not accept_template_deviation:
        raise PaperEngineError("替换将偏离模板，请确认后重试",gaps=warnings,status=409,code="template_deviation_confirmation_required")
    item.question_id=chosen.id;item.q_type=value(chosen.q_type)
    item.tag_snapshot_json=build_tag_snapshot(chosen);item.content_snapshot_json=build_content_snapshot(chosen)
    order_items(paper.items,paper.template_snapshot_json["parts"])
    persist_warnings(paper,rules.warnings())
    await db.commit();return await _load_paper(db,paper_id)

async def reshuffle_paper(db,*,paper_id,viewer=None):
    paper=await _load_paper(db,paper_id,lock=True);ensure_draft(paper)
    snap=paper.template_snapshot_json
    template=SimpleNamespace(**{**snap,"id":paper.batch.template_id,"subject_id":paper.subject_id,
                               "enabled":True,"schema_version":2,"parts_json":snap["parts"],"scope_json":paper.batch.scope_json})
    excluded=set()
    if paper.batch.cross_set_dedup:
        excluded=set((await db.execute(select(ExamPaperItem.question_id).join(ExamPaper)
                 .where(ExamPaper.batch_id==paper.batch_id,ExamPaper.id!=paper.id).with_for_update())).scalars())
    report,plans=await prepare(db,template=template,scope=paper.batch.scope_json,viewer=viewer,
                              excluded=excluded,seed=str(paper.seed),lock=True)
    if not report["feasible"]:raise PaperEngineError(report["gaps"][0]["message"],gaps=report["gaps"])
    await verify_selected(db, plans)
    for old in list(paper.items):await db.delete(old)
    await db.flush()
    for i in plans[1]:
        db.add(ExamPaperItem(paper_id=paper.id,question_id=i.question.id,part_key=i.part_key,section_key=i.section_key,
            q_type=i.q_type,seq=i.seq,score=i.score,tag_snapshot_json=build_tag_snapshot(i.question),
            content_snapshot_json=build_content_snapshot(i.question)))
    paper.actual_total_score=sum((i.score for i in plans[1]),Decimal(0))
    await db.commit();db.expire(paper,["items"]);return await _load_paper(db,paper_id)
