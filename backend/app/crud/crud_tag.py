from typing import Optional, Union, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.services.tag_assignment import validate_group
from app.models.question import question_tags
from app.models.paper_template import PaperTemplateTagRef
from app.crud.base import CRUDBase
from app.models.tag import Tag
from app.schemas.tag import TagCreate, TagUpdate
from app.services.activity_logger import log_activity

class CRUDTag(CRUDBase[Tag, TagCreate, TagUpdate]):
    async def get_multi_by_subject(
        self, db: AsyncSession, *, subject_id: int, skip: int = 0, limit: Optional[int] = 100,
        category_id: Optional[int] = None, enabled: Optional[bool] = None, keyword: Optional[str] = None,
    ) -> List[Tag]:
        query = select(self.model).where(self.model.subject_id == subject_id)
        if enabled is not None:
            query = query.where(self.model.enabled.is_(enabled))
        if keyword:
            query = query.where(self.model.name.contains(keyword))
        if category_id is not None:
            query = query.where(self.model.category_id == category_id)
        query = query.offset(skip)
        if limit is not None:
            query = query.limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def count_by_subject(
        self, db: AsyncSession, *, subject_id: int, category_id: Optional[int] = None, enabled: Optional[bool] = None, keyword: Optional[str] = None
    ) -> int:
        query = select(func.count()).select_from(self.model).where(self.model.subject_id == subject_id)
        if enabled is not None:
            query = query.where(self.model.enabled.is_(enabled))
        if keyword:
            query = query.where(self.model.name.contains(keyword))
        if category_id is not None:
            query = query.where(self.model.category_id == category_id)
        result = await db.execute(query)
        return result.scalar_one()

    async def get_by_name_in_subject(
        self, db: AsyncSession, *, name: str, subject_id: int
    ) -> Optional[Tag]:
        result = await db.execute(
            select(self.model).where(
                self.model.name == name, self.model.subject_id == subject_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, db: AsyncSession, *, obj_in: TagCreate, user_id: Optional[int] = None) -> Tag:
        await validate_group(db,obj_in.category_id,obj_in.subject_id)
        db_obj = Tag(**obj_in.model_dump())
        if user_id:
            db_obj.created_by = user_id
            db_obj.updated_by = user_id
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        await log_activity(db, user_id, "create", "tag", db_obj.id, details=obj_in.model_dump())
        await db.commit()
        return db_obj

    async def update(
        self, db: AsyncSession, *, db_obj: Tag, obj_in: Union[TagUpdate, Dict[str, Any]], user_id: Optional[int] = None
    ) -> Tag:
        data = dict(obj_in) if isinstance(obj_in,dict) else obj_in.model_dump(exclude_unset=True)
        await validate_group(db,data.get("category_id",db_obj.category_id),db_obj.subject_id)
        if data.get("name"):
            data["name"]=data["name"].strip()
            other=await self.get_by_name_in_subject(db,name=data["name"],subject_id=db_obj.subject_id)
            if other and other.id != db_obj.id: raise ValueError("同学科标签名称已存在")
        obj_in=data
        if user_id:
            db_obj.updated_by = user_id
        # subject_id 不允许通过更新迁移，避免跨学科命名冲突
        if isinstance(obj_in, dict):
            obj_in.pop("subject_id", None)
        updated_obj = await super().update(db, db_obj=db_obj, obj_in=obj_in)
        details = obj_in if isinstance(obj_in, dict) else obj_in.model_dump(exclude_unset=True)
        await log_activity(db, user_id, "update", "tag", updated_obj.id, details=details)
        await db.commit()
        return updated_obj

    async def remove(self, db: AsyncSession, *, id: int, user_id: Optional[int] = None) -> Tag:
        obj = (await db.execute(select(self.model).where(self.model.id==id).with_for_update())).scalar_one_or_none()
        if obj:
            refs=await self.references(db,id)
            if not refs['can_delete']: raise ValueError('标签仍被题目或模板引用，请先移除引用或停用')
            await db.delete(obj)
            await db.commit()
            await log_activity(db, user_id, "delete", "tag", id)
            await db.commit()
        return obj

    async def references(self,db,id):
        qc=(await db.execute(select(func.count()).select_from(question_tags).where(question_tags.c.tag_id==id))).scalar_one()
        tc=(await db.execute(select(func.count()).select_from(PaperTemplateTagRef).where(PaperTemplateTagRef.tag_id==id))).scalar_one()
        return {"tag_id":id,"question_count":qc,"template_count":tc,"can_delete":not(qc or tc)}

tag = CRUDTag(Tag)
