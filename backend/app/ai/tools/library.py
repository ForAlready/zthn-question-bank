"""知识点与标签的只读 AI 工具。

不迁到 capability 层:纯读、无授权判定、无领域不变量,不满足纳入标准。
"""
from typing import Any, Dict
import logging

from sqlalchemy import select

from app.ai.contracts import ToolResult, ToolSpec
from app.ai.tools.registry import register
from app.capabilities.context import ExecutionContext
from app.models.tag import Tag
from app.models.tag_category import TagCategory
from app.services.kp_retriever import KnowledgePointRetriever

logger = logging.getLogger(__name__)

SEARCH_KNOWLEDGE_POINTS_PARAMS = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索关键词或查询语句。"
        },
        "limit": {
            "type": "integer",
            "description": "返回结果的数量 (默认为 5)。",
            "default": 5
        }
    },
    "required": ["query"]
}

GET_AVAILABLE_TAGS_PARAMS = {
    "type": "object",
    "properties": {},
    "required": []
}


async def search_knowledge_points(ctx: ExecutionContext, args: Dict[str, Any]) -> ToolResult:
    query = args.get("query")
    limit = args.get("limit", 5)

    if not query:
        return ToolResult.text("Please provide a query.")

    results = await KnowledgePointRetriever.retrieve(query=query, limit=limit)

    if not results or not results.get("documents") or not results["documents"][0]:
        return ToolResult.text("No knowledge points found.")

    candidates = results["documents"][0]
    distances = results["distances"][0] if results.get("distances") else []

    output = []
    for i, text in enumerate(candidates):
        dist = distances[i] if i < len(distances) else "N/A"
        output.append(f"{i+1}. {text} (Distance: {dist})")

    return ToolResult(content="\n".join(output))


async def get_available_tags(ctx: ExecutionContext, args: Dict[str, Any]) -> ToolResult:
    from app.core.permissions import can, Permission
    if ctx.subject_id is None:
        return ToolResult.text("请先选择当前学科，再查询可用标签。")
    if not can(ctx.actor, Permission.VIEW_QUESTION, subject_id=ctx.subject_id):
        return ToolResult.text("无权访问当前学科标签。")
    categories = (await ctx.db.execute(select(TagCategory).where(TagCategory.subject_id == ctx.subject_id)
                                      .order_by(TagCategory.sort_order))).scalars().all()
    tags = (await ctx.db.execute(select(Tag).where(Tag.subject_id == ctx.subject_id, Tag.enabled.is_(True))
                                .order_by(Tag.id))).scalars().all()
    groups = {cat.id: cat.name for cat in categories}
    lines = {}
    for tag in tags:
        lines.setdefault(groups.get(tag.category_id, "未分组"), []).append(f"{tag.name} (ID={tag.id})")
    return ToolResult.text("\n".join(f"- **{group}**: {', '.join(names)}" for group,names in lines.items()) or "当前学科没有启用标签。")


register(ToolSpec(
    name="search_knowledge_points",
    description="在向量知识库中搜索相关的知识点。当你需要为题目关联知识点，或者需要了解某个概念在知识库中的具体表述时，使用此工具。",
    parameters=SEARCH_KNOWLEDGE_POINTS_PARAMS,
    handler=search_knowledge_points,
))

register(ToolSpec(
    name="get_available_tags",
    description="获取当前学科启用的扁平标签（分组仅供展示）。当你需要为题目打标签时，请先调用此工具查看有哪些标签可用，然后选择合适的标签名称。",
    parameters=GET_AVAILABLE_TAGS_PARAMS,
    handler=get_available_tags,
))
