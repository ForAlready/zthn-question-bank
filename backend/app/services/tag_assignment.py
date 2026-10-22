"""Tag validation, matching and template reference maintenance."""
from sqlalchemy import delete, select

from app.models.tag import Tag
from app.models.tag_category import TagCategory
from app.models.paper_template import PaperTemplateTagRef
from app.schemas.tag_filter import TagFilter


async def resolve_tags(db, ids, *, subject_id, existing_ids=(), allow_disabled=False):
    ids = set(ids or [])
    if not ids:
        return []
    rows = (await db.execute(select(Tag).where(Tag.id.in_(sorted(ids))).with_for_update())).scalars().all()
    if len(rows) != len(ids) or any(t.subject_id != subject_id for t in rows):
        raise ValueError("标签不存在或不可用于当前学科")
    if not allow_disabled and any(not t.enabled and t.id not in existing_ids for t in rows):
        raise ValueError("标签已停用，请移除或替换")
    return list(rows)


async def validate_group(db, category_id, subject_id):
    if category_id is not None:
        group = await db.get(TagCategory, category_id)
        if not group or group.subject_id != subject_id:
            raise ValueError("标签分组不可用于当前学科")


def template_tag_ids(parts, scope):
    ids = set(TagFilter.model_validate(scope or {}).tag_ids)
    for part in parts:
        for section in part["sections"]:
            ids.update(TagFilter.model_validate(section.get("tag_filter", {})).tag_ids)
    return ids


async def sync_template_tags(db, template):
    ids = template_tag_ids(template.parts_json, template.scope_json)
    await resolve_tags(db, ids, subject_id=template.subject_id)
    await db.execute(delete(PaperTemplateTagRef).where(PaperTemplateTagRef.template_id == template.id))
    db.add_all([PaperTemplateTagRef(template_id=template.id, tag_id=i) for i in sorted(ids)])
