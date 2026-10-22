"""组卷模板 CRUD + 系统默认恢复出厂。"""
from typing import Any, List, Optional
from pydantic import ValidationError
from app.services.tag_assignment import sync_template_tags
from app.services.paper_engine.generate import preflight, PaperEngineError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError

from app import crud, models, schemas
from app.api import deps
from app.core.permissions import Permission
from app.services.paper_template_factory import (
    FactoryRestoreError,
    build_junior_factory_parts,
)
from app.services.paper_template_validate import (
    TemplateValidationError,
    validate_template_structure,
)

router = APIRouter()


def _validation_http(exc: TemplateValidationError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"message": exc.message, "errors": exc.errors},
    )


@router.get("", response_model=List[schemas.PaperTemplateOut])
async def list_paper_templates(
    db: deps.SessionDep,
    subject_id: int = Query(...),
    enabled: Optional[bool] = Query(None),
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=subject_id)
    return await crud.paper_template.get_by_subject(
        db, subject_id=subject_id, enabled=enabled
    )


@router.post("", response_model=schemas.PaperTemplateOut)
async def create_paper_template(
    *,
    db: deps.SessionDep,
    body: schemas.PaperTemplateCreate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    deps.require(
        current_user, Permission.MANAGE_PAPER_TEMPLATE, subject_id=body.subject_id
    )
    try:
        validate_template_structure(total_score=body.total_score, parts=body.parts)
    except TemplateValidationError as exc:
        raise _validation_http(exc) from exc

    subject = await crud.subject.get(db=db, id=body.subject_id)
    if not subject:
        raise HTTPException(status_code=404, detail="学科不存在")

    try:
        return await crud.paper_template.create_template(
            db, obj_in=body, created_by=current_user.id
        )
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(400,detail=str(exc)) from exc
    except IntegrityError:
        raise HTTPException(status_code=400, detail="同学科下已存在同名模板")


@router.get("/{id}", response_model=schemas.PaperTemplateOut)
async def get_paper_template(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    tmpl = await crud.paper_template.get(db=db, id=id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    deps.require(current_user, Permission.VIEW_QUESTION, subject_id=tmpl.subject_id)
    return tmpl


@router.patch("/{id}", response_model=schemas.PaperTemplateOut)
async def update_paper_template(
    *,
    db: deps.SessionDep,
    id: int,
    body: schemas.PaperTemplateUpdate,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    tmpl = await crud.paper_template.get(db=db, id=id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    deps.require(
        current_user, Permission.MANAGE_PAPER_TEMPLATE, subject_id=tmpl.subject_id
    )

    data = body.model_dump(exclude_unset=True)
    # PATCH 允许只传部分字段，须将未传的总分/分区与现有模板合并后校验整体一致性。
    total_score = data.get("total_score", tmpl.total_score)
    parts = data.get("parts", tmpl.parts_json)
    try:
        validate_template_structure(total_score=total_score, parts=parts)
    except TemplateValidationError as exc:
        raise _validation_http(exc) from exc

    try:
        return await crud.paper_template.update_template(db, db_obj=tmpl, obj_in=body)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(400,detail=str(exc)) from exc
    except IntegrityError:
        raise HTTPException(status_code=400, detail="同学科下已存在同名模板")


@router.delete("/{id}", response_model=schemas.PaperTemplateOut)
async def delete_paper_template(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    tmpl = await crud.paper_template.get(db=db, id=id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    deps.require(
        current_user, Permission.MANAGE_PAPER_TEMPLATE, subject_id=tmpl.subject_id
    )
    if tmpl.is_system_default:
        raise HTTPException(status_code=400, detail="系统默认模板不可删除")

    try:
        await db.delete(tmpl)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, detail="模板已有考试试卷引用，请停用模板以保留历史追溯") from exc
    return tmpl


@router.post("/{id}/restore-factory", response_model=schemas.PaperTemplateOut)
async def restore_factory_paper_template(
    *,
    db: deps.SessionDep,
    id: int,
    current_user: models.User = Depends(deps.get_current_active_user),
) -> Any:
    tmpl = await crud.paper_template.get(db=db, id=id)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    deps.require(
        current_user, Permission.MANAGE_PAPER_TEMPLATE, subject_id=tmpl.subject_id
    )
    if not tmpl.is_system_default:
        raise HTTPException(status_code=400, detail="仅系统默认模板支持恢复出厂")

    try:
        factory = await build_junior_factory_parts(db, subject_id=tmpl.subject_id)
    except FactoryRestoreError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    validate_template_structure(
        total_score=factory["total_score"], parts=factory["parts_json"]
    )
    for key, value in factory.items():
        setattr(tmpl, key, value)
    db.add(tmpl)
    await db.flush()
    await sync_template_tags(db,tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


@router.post("/{id}/preflight")
async def preflight_template(id:int,body:dict,db:deps.SessionDep,
                              current_user:models.User=Depends(deps.get_current_active_user)):
    tmpl=await crud.paper_template.get(db=db,id=id)
    if not tmpl:raise HTTPException(404,detail="模板不存在")
    deps.require(current_user,Permission.GENERATE_PAPER,subject_id=tmpl.subject_id)
    if "template_id" in body:raise HTTPException(422,detail="模板 ID 由路径确定")
    try:
        request=schemas.ExamPaperGenerateRequest.model_validate({"template_id":id,**body})
    except ValidationError as exc:raise HTTPException(422,detail=str(exc)) from exc
    try:
        return await preflight(db,template=tmpl,n_sets=request.n_sets,cross_set_dedup=request.cross_set_dedup,
            scope=request.scope if "scope" in request.model_fields_set else None,seed=request.seed,viewer=current_user)
    except PaperEngineError as exc:
        raise HTTPException(exc.status,detail={"code":exc.code,"message":exc.message,"gaps":exc.gaps}) from exc
