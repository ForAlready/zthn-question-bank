"""考试试卷：生成、改分、换题、重抽、定稿、详情、导出。"""
import os
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from app import crud, models, schemas
from app.api import deps
from app.core.permissions import Permission
from app.models.exam_paper import ExamPaper, ExamPaperBatch
from app.services.activity_logger import log_activity
from app.services.paper_engine.replacement import ReplacementRules, forbidden_ids, eligible
from app.services.question_content import parse_json_field
from app.services.exporting.exam_paper_contracts import MODE_WITH_ANSWERS
from app.services.exporting.exam_paper_export import export_exam_paper_docx
from app.services.paper_engine import (
    PaperEngineError,
    finalize_paper,
    generate_batch,
    replace_item,
    reshuffle_paper,
    update_item_score,
)

router = APIRouter()


def _engine_http(exc: PaperEngineError) -> HTTPException:
    return HTTPException(
        status_code=exc.status,
        detail={"code":exc.code,"message": exc.message, "gaps": exc.gaps},
    )


def _assert_export_tempfile(path: str) -> str:
    """导出路径必须落在系统临时目录且为 .docx，防止误用用户可控路径。"""
    real = os.path.realpath(path)
    tmp_root = os.path.realpath(tempfile.gettempdir())
    try:
        under_tmp = os.path.commonpath([real, tmp_root]) == tmp_root
    except ValueError:
        under_tmp = False
    if not under_tmp or not real.lower().endswith(".docx") or not os.path.isfile(real):
        raise HTTPException(status_code=500, detail="导出文件无效")
    return real


async def _get_paper_or_404(db: deps.SessionDep, paper_id: int) -> ExamPaper:
    result = await db.execute(
        select(ExamPaper)
        .options(
            selectinload(ExamPaper.items),
            selectinload(ExamPaper.batch),
        )
        .where(ExamPaper.id == paper_id)
    )
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return paper


@router.post("/generate", response_model=schemas.ExamPaperBatchOut)
async def generate_exam_papers(
    *,
    db: deps.SessionDep,
    body: schemas.ExamPaperGenerateRequest,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    tmpl = await crud.paper_template.get(db=db, id=body.template_id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    deps.require(current_user, Permission.GENERATE_PAPER, subject_id=tmpl.subject_id)

    try:
        batch = await generate_batch(
            db,
            template=tmpl,
            created_by=current_user.id,
            title=body.title,
            n_sets=body.n_sets,
            cross_set_dedup=body.cross_set_dedup,
            scope=body.scope if "scope" in body.model_fields_set else None,
            duration_minutes=body.duration_minutes,
            seed=body.seed,
            viewer=current_user,
        )
    except PaperEngineError as exc:
        await db.rollback()
        raise _engine_http(exc) from exc
    return batch


@router.get("/batches/{batch_id}", response_model=schemas.ExamPaperBatchOut)
async def get_exam_paper_batch(
    *,
    db: deps.SessionDep,
    batch_id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    result = await db.execute(
        select(ExamPaperBatch)
        .options(selectinload(ExamPaperBatch.papers).selectinload(ExamPaper.items))
        .where(ExamPaperBatch.id == batch_id)
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="试卷批次不存在")
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=batch.subject_id)
    return batch


@router.get("/{id}", response_model=schemas.ExamPaperOut)
async def get_exam_paper(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    paper = await _get_paper_or_404(db, id)
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=paper.subject_id)
    return paper


@router.get("/{id}/items/{item_id}/candidates")
async def replacement_candidates(
    db:deps.SessionDep,id:int,item_id:int,keyword:str="",q_type:str|None=None,
    tag_ids:list[int]=Query(default=[]),tag_match:str=Query("any",pattern="^(any|all)$"),
    tag_filter_override:bool=False,scope_override:bool=False,
    scope_tag_ids:list[int]=Query(default=[]),scope_tag_match:str=Query("any",pattern="^(any|all)$"),
    page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=100),
    current_user:models.User=Depends(deps.get_current_active_user)):
    from app.schemas.tag_filter import TagFilter
    from app.services.tag_assignment import resolve_tags
    paper=await _get_paper_or_404(db,id)
    deps.require(current_user,Permission.GENERATE_PAPER,subject_id=paper.subject_id)
    if paper.status=="final":raise HTTPException(409,detail="试卷已定稿")
    item=next((i for i in paper.items if i.id==item_id),None)
    if not item:raise HTTPException(404,detail="题位不存在")
    rules=await ReplacementRules.load(db,paper)
    section=rules.section(item)
    if not section:raise HTTPException(400,detail="来源规则不存在")
    condition=TagFilter(tag_ids=tag_ids,match=tag_match) if tag_filter_override else TagFilter.model_validate(section["tag_filter"])
    scope=TagFilter(tag_ids=scope_tag_ids,match=scope_tag_match) if scope_override else TagFilter.model_validate(paper.batch.scope_json or {})
    try:
        await resolve_tags(db,condition.tag_ids+scope.tag_ids,subject_id=paper.subject_id)
    except ValueError as exc:raise HTTPException(400,detail=str(exc)) from exc
    forbidden=await forbidden_ids(db,paper,item)
    query=await crud.question._get_filter_query(db,subject_id=paper.subject_id,q_type=q_type or item.q_type,
          keyword=keyword or None,status="published",viewer=current_user)
    rows=(await db.execute(query.order_by(models.Question.id.desc()))).scalars().unique().all()
    rows=[q for q in rows if eligible(q,paper=paper,forbidden=forbidden,viewer=current_user)
          and condition.matches(t.id for t in q.tags) and scope.matches(t.id for t in q.tags)]
    return {"items":[{"id":q.id,"content":parse_json_field(q.content),"q_type":q.q_type,
                     "tags":[{"id":t.id,"name":t.name} for t in q.tags],"warnings":rules.warnings(item,q)}
                    for q in rows[(page-1)*size:page*size]],"total":len(rows),"page":page,"size":size}


@router.patch("/{id}/items/{item_id}", response_model=schemas.ExamPaperOut)
async def patch_exam_paper_item_score(
    *,
    db: deps.SessionDep,
    id: int,
    item_id: int,
    body: schemas.ExamPaperItemScoreUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    paper = await _get_paper_or_404(db, id)
    deps.require(current_user, Permission.GENERATE_PAPER, subject_id=paper.subject_id)
    try:
        return await update_item_score(
            db, paper_id=id, item_id=item_id, score=body.score
        )
    except PaperEngineError as exc:
        raise _engine_http(exc) from exc


@router.post("/{id}/items/{item_id}/replace", response_model=schemas.ExamPaperOut)
async def replace_exam_paper_item(
    *,
    db: deps.SessionDep,
    id: int,
    item_id: int,
    body: schemas.ExamPaperItemReplaceRequest,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    paper = await _get_paper_or_404(db, id)
    deps.require(current_user, Permission.GENERATE_PAPER, subject_id=paper.subject_id)
    try:
        return await replace_item(
            db,
            paper_id=id,
            item_id=item_id,
            mode=body.mode,
            question_id=body.question_id,
            filters=body.filters,
            viewer=current_user,
            accept_template_deviation=body.accept_template_deviation,
        )
    except PaperEngineError as exc:
        await db.rollback()
        raise _engine_http(exc) from exc


@router.post("/{id}/reshuffle", response_model=schemas.ExamPaperOut)
async def reshuffle_exam_paper(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    paper = await _get_paper_or_404(db, id)
    deps.require(current_user, Permission.GENERATE_PAPER, subject_id=paper.subject_id)
    try:
        return await reshuffle_paper(db, paper_id=id, viewer=current_user)
    except PaperEngineError as exc:
        await db.rollback()
        raise _engine_http(exc) from exc


@router.post("/{id}/finalize", response_model=schemas.ExamPaperOut)
async def finalize_exam_paper(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    paper = await _get_paper_or_404(db, id)
    deps.require(current_user, Permission.GENERATE_PAPER, subject_id=paper.subject_id)
    try:
        return await finalize_paper(db, paper_id=id, user_id=current_user.id)
    except PaperEngineError as exc:
        raise _engine_http(exc) from exc


@router.post("/{id}/export")
async def export_exam_paper(
    *,
    db: deps.SessionDep,
    id: int,
    body: schemas.ExamPaperExportQuery,
    request: Request,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    """导出试卷 Word（AC-07/AC-08）。每次请求后端重新鉴权并写审计。"""
    paper = await _get_paper_or_404(db, id)
    include_analysis = bool(body.include_analysis) and body.mode == MODE_WITH_ANSWERS

    if body.mode == MODE_WITH_ANSWERS:
        deps.require(
            current_user, Permission.EXPORT_WITH_ANSWERS, subject_id=paper.subject_id
        )
    else:
        deps.require(
            current_user,
            Permission.EXPORT_PAPER_WITHOUT_ANSWERS,
            subject_id=paper.subject_id,
        )

    result = export_exam_paper_docx(
        paper, mode=body.mode, include_analysis=include_analysis
    )
    safe_path = _assert_export_tempfile(result.path)

    await log_activity(
        db,
        user_id=current_user.id,
        action="export",
        resource_type="exam_paper",
        resource_id=paper.id,
        details={
            "mode": body.mode,
            "include_analysis": include_analysis,
            "filename": result.filename,
            "set_index": paper.set_index,
        },
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    def cleanup() -> None:
        if os.path.exists(safe_path):
            os.remove(safe_path)

    return FileResponse(
        path=safe_path,
        filename=result.filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        background=BackgroundTask(cleanup),
    )
