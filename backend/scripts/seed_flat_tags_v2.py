"""Idempotent flat-tag/default-template initialization. Does not label existing questions."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.models.subject import Subject
from app.models.tag import Tag
from app.models.tag_category import TagCategory
from app.models.paper_template import PaperTemplate
from app.services.paper_template_factory import build_junior_factory_parts, JUNIOR_SEED_KEY
from app.services.tag_assignment import sync_template_tags
from app.db.session import SessionLocal

GROUPS = {
    "内容领域": [("业务", "business"), ("技术", "technical")],
    "业务主题": [("闲置买卖", "idle_trade"), ("循环物资库", "recycled_inventory"), ("租赁", "lease"),
                 ("处置", "disposal"), ("租售店铺", "store_lease")],
    "技术主题": [("前端", "frontend"), ("后端", "backend"), ("测试", "testing"),
                 ("设计", "design"), ("项目管理", "project_management")],
    "用途": [("面试", "interview"), ("岗位考核", "post_assessment")],
}


async def seed_subject(db, subject):
    for order, (name, tags) in enumerate(GROUPS.items()):
        group = (await db.execute(select(TagCategory).where(TagCategory.subject_id == subject.id, TagCategory.name == name))).scalar_one_or_none()
        if not group:
            group = TagCategory(subject_id=subject.id, name=name, sort_order=order)
            db.add(group)
            await db.flush()
        for label, key in tags:
            tag = (await db.execute(select(Tag).where(Tag.subject_id == subject.id, Tag.seed_key == key))).scalar_one_or_none()
            if tag:
                continue
            tag = (await db.execute(select(Tag).where(Tag.subject_id == subject.id, Tag.name == label))).scalar_one_or_none()
            if tag:
                if tag.seed_key and tag.seed_key != key:
                    raise ValueError(f"标签种子冲突：{key}")
                tag.seed_key = key
            else:
                db.add(Tag(subject_id=subject.id, category_id=group.id, name=label, seed_key=key, enabled=True))
    await db.flush()
    template = (await db.execute(select(PaperTemplate).where(PaperTemplate.subject_id == subject.id,
                        PaperTemplate.seed_key == JUNIOR_SEED_KEY))).scalar_one_or_none()
    if not template:
        factory = await build_junior_factory_parts(db, subject_id=subject.id)
        template = PaperTemplate(subject_id=subject.id, is_system_default=True, seed_key=JUNIOR_SEED_KEY, **factory)
        db.add(template)
        await db.flush()
        await sync_template_tags(db, template)
    return template


async def run():
    async with SessionLocal() as db:
        for subject in (await db.execute(select(Subject))).scalars():
            await seed_subject(db, subject)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(run())
