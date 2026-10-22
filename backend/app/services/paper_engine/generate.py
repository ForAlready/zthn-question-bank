"""Batch-wide matching, read-only preflight, and atomic persistence."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib, json, random, secrets
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.question import Question, question_tags
from app.models.tag import Tag
from app.models.paper_template import PaperTemplate
from app.models.exam_paper import ExamPaperBatch,ExamPaper,ExamPaperItem
from app.schemas.tag_filter import TagFilter
from app.crud.crud_question import visible_questions_filter
from app.services.tag_assignment import resolve_tags,template_tag_ids
from app.services.paper_template_validate import validate_template_structure,TemplateValidationError
from .assign import bipartite_match
from .answerable import is_answerable_question
from .snapshot import build_content_snapshot,build_tag_snapshot,order_items,value,TYPE_NAMES

class PaperEngineError(Exception):
    def __init__(self,message,*,gaps=None,code="invalid_paper",status=400):
        super().__init__(message);self.message=message;self.gaps=gaps or [message];self.code=code;self.status=status

@dataclass
class PlannedItem:
    part_key:str
    section_key:str
    q_type:str
    score:Decimal
    question:object
    seq:int=0
    fingerprint:str=""

CHECK_FIELDS = ("content_revision", "content", "options", "answer", "thinking", "analysis", "summary",
                "q_type", "status", "subject_id", "visibility", "created_by", "deleted_at", "needs_review")

def question_fingerprint(question, tag_ids):
    data = {key: value(getattr(question, key)) for key in CHECK_FIELDS}
    data["tag_ids"] = sorted(tag_ids)
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()

async def verify_selected(db, plans):
    """Use current locking reads, including associations, immediately before writes.

    ORM identity-map values and MySQL repeatable-read snapshots must not hide
    content/status/tag changes that occurred since the planning read.
    """
    selected = {i.question.id: i for items in plans.values() for i in items}
    if not selected:
        return
    ids = sorted(selected)
    rows = (await db.execute(select(*[getattr(Question, key) for key in ("id", *CHECK_FIELDS)])
                            .where(Question.id.in_(ids)).order_by(Question.id).with_for_update())).all()
    associations = (await db.execute(select(question_tags).where(question_tags.c.question_id.in_(ids))
                                     .order_by(question_tags.c.question_id, question_tags.c.tag_id).with_for_update())).all()
    tags = {qid: [] for qid in ids}
    for qid, tid in associations:
        tags[qid].append(tid)
    if len(rows) != len(ids) or any(question_fingerprint(row, tags[row.id]) != selected[row.id].fingerprint for row in rows):
        raise PaperEngineError("候选题目在规划后发生变化，请重新预检并生成", code="candidate_changed", status=409)
    # Lock and refresh tag names for immutable historical snapshots.
    tids = sorted({tid for values in tags.values() for tid in values})
    if tids:
        await db.execute(select(Tag).where(Tag.id.in_(tids)).order_by(Tag.id).with_for_update()
                         .execution_options(populate_existing=True))

def template_snapshot(t):
    return {"id":t.id,"schema_version":2,"name":t.name,"total_score":float(t.total_score),
            "parts":t.parts_json,"scope":t.scope_json or {},"duration_minutes":t.duration_minutes,
            "instructions":t.instructions,"seed_key":t.seed_key,"is_system_default":t.is_system_default}

def conflict_groups(pools,matched,slots):
    owner={q:i for i,q in enumerate(matched) if q is not None}
    groups=[]
    for root,q in enumerate(matched):
        if q is not None:continue
        reached={root};questions=set();todo=[root]
        while todo:
            i=todo.pop()
            for candidate in pools[i]:
                questions.add(candidate)
                j=owner.get(candidate)
                if j is not None and j not in reached:reached.add(j);todo.append(j)
        for a,b in list(groups):
            if a&reached or b&questions:
                reached|=a;questions|=b;groups.remove((a,b))
        groups.append((reached,questions))
    return [{"code":"overlapping_pool_conflict","section_keys":sorted({slots[i][2].key for i in a}),
             "required":len(a),"available":len(b),"deficit":len(a)-len(b),
             "message":f"交叉规则需{len(a)}个题位，相关题池仅{len(b)}道唯一题目，缺{len(a)-len(b)}题"}
            for a,b in groups]

async def prepare(db,*,template,n_sets=1,cross_set_dedup=True,scope=None,viewer=None,seed=None,excluded=(),lock=False):
    if not template.enabled:raise PaperEngineError("模板已停用",code="template_disabled")
    if template.schema_version!=2:raise PaperEngineError("旧模板需要重建",code="legacy_template_requires_rebuild")
    try:
        parts=validate_template_structure(total_score=template.total_score,parts=template.parts_json)
        effective=TagFilter.model_validate(template.scope_json or {}) if scope is None else TagFilter.model_validate(scope)
        await resolve_tags(db,template_tag_ids(template.parts_json,effective.model_dump()),subject_id=template.subject_id)
    except ValueError as exc:raise PaperEngineError(str(exc)) from exc
    stmt=select(Question).options(selectinload(Question.tags)).where(Question.subject_id==template.subject_id,Question.deleted_at.is_(None))
    if viewer is not None:stmt=stmt.where(visible_questions_filter(viewer))
    if lock:stmt=stmt.with_for_update()
    questions=list((await db.execute(stmt.order_by(Question.id))).scalars().unique())
    published=[q for q in questions if q.status=="published"]
    answerable=[q for q in published if is_answerable_question(q) and q.id not in excluded]
    slots=[];pools=[];rules=[];byid={q.id:q for q in answerable}
    for p in parts:
        for s in p.sections:
            typed=[q for q in answerable if value(q.q_type)==value(s.q_type)]
            scoped=[q for q in typed if effective.matches(t.id for t in q.tags)]
            filtered=[q for q in scoped if s.tag_filter.matches(t.id for t in q.tags)]
            ids=[q.id for q in filtered]
            rules.append({"part_key":p.key,"section_key":s.key,"q_type":value(s.q_type),
                          "tag_filter":s.tag_filter.model_dump(),"count_per_set":s.count,
                          "requested_slots":s.count*n_sets,"candidate_count":len(ids),
                          "stages":{"visible":len(questions),"published":len(published),"answerable":len(answerable),
                                    "q_type":len(typed),"scope":len(scoped),"tags":len(filtered)}})
            for setindex in range(1,n_sets+1):
                for _ in range(s.count):slots.append((setindex,p,s));pools.append(ids)
    rng=random.Random(seed)
    matched=[None]*len(slots)
    if cross_set_dedup:
        matched=bipartite_match(pools,rng=rng)
    else:
        for index in range(1,n_sets+1):
            positions=[i for i,slot in enumerate(slots) if slot[0]==index]
            result=bipartite_match([pools[i] for i in positions],rng=rng)
            for i,q in zip(positions,result):matched[i]=q
    gaps=[]
    for r in rules:
        need=r["requested_slots"] if cross_set_dedup else r["count_per_set"]
        if r["candidate_count"]<need:
            gaps.append({"code":"insufficient_candidates","section_keys":[r["section_key"]],"required":need,
                         "available":r["candidate_count"],"deficit":need-r["candidate_count"],
                         "message":f"规则 {r['section_key']} 可用{r['candidate_count']}题，需要{need}题"})
    if any(q is None for q in matched) and not gaps:
        if cross_set_dedup:gaps=conflict_groups(pools,matched,slots)
        else:
            pos=[i for i,x in enumerate(slots) if x[0]==1]
            gaps=conflict_groups([pools[i] for i in pos],[matched[i] for i in pos],[slots[i] for i in pos])
    report={"template_id":template.id,"schema_version":2,"n_sets":n_sets,"cross_set_dedup":cross_set_dedup,
            "effective_scope":effective.model_dump(),"feasible":not gaps,
            "required_slots":len(slots),"matched_slots":sum(q is not None for q in matched),"rules":rules,"gaps":gaps}
    plans={i:[] for i in range(1,n_sets+1)}
    if not gaps:
        for (index,p,s),qid in zip(slots,matched):
            q = byid[qid]
            plans[index].append(PlannedItem(p.key,s.key,value(s.q_type),s.score_each,q,len(plans[index])+1,
                                           question_fingerprint(q, (t.id for t in q.tags))))
        for items in plans.values():order_items(items,template.parts_json)
    return report,plans

async def preflight(db,**kwargs):
    report,_=await prepare(db,**kwargs)
    return report

async def load_batch(db,batch_id):
    return (await db.execute(select(ExamPaperBatch).options(selectinload(ExamPaperBatch.papers).selectinload(ExamPaper.items))
                            .where(ExamPaperBatch.id==batch_id))).scalar_one()

async def generate_batch(db,*,template,created_by,title=None,n_sets=1,cross_set_dedup=True,scope=None,duration_minutes=None,seed=None,viewer=None):
    template = (await db.execute(select(PaperTemplate).where(PaperTemplate.id == template.id)
                                .with_for_update().execution_options(populate_existing=True))).scalar_one()
    seed=seed or secrets.token_hex(16)
    report,plans=await prepare(db,template=template,n_sets=n_sets,cross_set_dedup=cross_set_dedup,
                               scope=scope,seed=seed,viewer=viewer,lock=True)
    if not report["feasible"]:raise PaperEngineError(report["gaps"][0]["message"],gaps=report["gaps"],code="insufficient_candidates")
    snap=template_snapshot(template)
    try:
        await verify_selected(db, plans)
        batch=ExamPaperBatch(subject_id=template.subject_id,template_id=template.id,n_sets=n_sets,
            cross_set_dedup=cross_set_dedup,scope_json=report["effective_scope"],template_snapshot_json=snap,seed=seed,created_by=created_by)
        db.add(batch);await db.flush()
        for index,items in plans.items():
            suffix=f"（{chr(64+index)}卷）" if n_sets>1 else ""
            paper=ExamPaper(batch_id=batch.id,subject_id=template.subject_id,title=(title or template.name)+suffix,
                set_index=index,status="draft",template_snapshot_json=snap,
                actual_total_score=sum((i.score for i in items),Decimal(0)),
                duration_minutes=duration_minutes if duration_minutes is not None else template.duration_minutes,
                instructions=template.instructions,seed=seed,created_by=created_by)
            db.add(paper);await db.flush()
            for i in items:
                db.add(ExamPaperItem(paper_id=paper.id,question_id=i.question.id,part_key=i.part_key,
                    section_key=i.section_key,q_type=i.q_type,seq=i.seq,score=i.score,
                    tag_snapshot_json=build_tag_snapshot(i.question),content_snapshot_json=build_content_snapshot(i.question)))
        await db.commit()
    except Exception:
        await db.rollback();raise
    return await load_batch(db,batch.id)
