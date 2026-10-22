"""组卷模板 CRUD。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.services.tag_assignment import sync_template_tags
from app.models.paper_template import PaperTemplate
from app.schemas.paper_template import PaperTemplateCreate, PaperTemplateUpdate
from app.services.paper_template_validate import parts_to_json


class CRUDPaperTemplate(CRUDBase[PaperTemplate, PaperTemplateCreate, PaperTemplateUpdate]):
    async def get_by_subject(
        self,
        db: AsyncSession,
        *,
        subject_id: int,
        enabled: Optional[bool] = None,
    ) -> List[PaperTemplate]:
        q = select(self.model).where(self.model.subject_id == subject_id)
        if enabled is not None:
            q = q.where(self.model.enabled.is_(enabled))
        q = q.order_by(self.model.is_system_default.desc(), self.model.id.asc())
        result = await db.execute(q)
        return list(result.scalars().all())

    async def get_by_seed_key(
        self, db: AsyncSession, *, subject_id: int, seed_key: str
    ) -> Optional[PaperTemplate]:
        result = await db.execute(
            select(self.model).where(
                self.model.subject_id == subject_id,
                self.model.seed_key == seed_key,
            )
        )
        return result.scalar_one_or_none()

    async def create_template(
        self,
        db: AsyncSession,
        *,
        obj_in: PaperTemplateCreate,
        created_by: Optional[int] = None,
        is_system_default: bool = False,
        seed_key: Optional[str] = None,
    ) -> PaperTemplate:
        db_obj = PaperTemplate(
            subject_id=obj_in.subject_id,
            name=obj_in.name,
            total_score=obj_in.total_score,
            parts_json=parts_to_json(obj_in.parts),
            scope_json=obj_in.scope.model_dump(mode="json"),
            duration_minutes=obj_in.duration_minutes,
            instructions=obj_in.instructions,
            enabled=obj_in.enabled,
            is_system_default=is_system_default,
            seed_key=seed_key,
            created_by=created_by,
        )
        db.add(db_obj)
        await db.flush()
        await sync_template_tags(db, db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update_template(
        self,
        db: AsyncSession,
        *,
        db_obj: PaperTemplate,
        obj_in: Union[PaperTemplateUpdate, Dict[str, Any]],
    ) -> PaperTemplate:
        if isinstance(obj_in, dict):
            data = dict(obj_in)
        else:
            data = obj_in.model_dump(mode="json", exclude_unset=True)

        if "parts" in data and data["parts"] is not None:
            data["parts_json"] = parts_to_json(data.pop("parts"))
        if "scope" in data:
            scope = data.pop("scope")
            data["scope_json"] = scope.model_dump(mode="json") if hasattr(scope,"model_dump") else scope

        for field, value in data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        db.add(db_obj)
        await db.flush()
        await sync_template_tags(db, db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj


paper_template = CRUDPaperTemplate(PaperTemplate)
