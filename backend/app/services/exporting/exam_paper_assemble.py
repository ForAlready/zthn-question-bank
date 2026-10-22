"""考试试卷装配：ExamPaper + content_snapshot → CompositionExportDoc（格式无关中间层）。

- without_answers：仅卷头、题干、选项、作答区；不装配答案/解析/「参考答案」。
- with_answers：正文后插入 page_break，再输出「参考答案」区；默认不含解析。
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from app.models.exam_paper import ExamPaper, ExamPaperItem
from app.services.exporting.answer import answer_spec_to_inline
from app.services.exporting.composition_assemble import (
    _parse_options,
    _resolve_option_columns,
)
from app.services.exporting.composition_contracts import (
    CompositionExportDoc,
    CompositionExportNode,
    ExportAnswerSpaceNode,
    ExportHeadingNode,
    ExportOption,
    ExportPageBreakNode,
    ExportQuestionNode,
    ExportRichTextNode,
)
from app.services.exporting.exam_paper_contracts import (
    ANSWER_SECTION_TITLE,
    MODE_WITH_ANSWERS,
    MODE_WITHOUT_ANSWERS,
    ExportMode,
)
from app.services.question_content_converter import rich_doc_to_plain_text

_OBJECTIVE_TYPES = frozenset({"single_choice", "multiple_choice", "true_false"})
_SUBJECTIVE_TYPES = frozenset({"fill_in_the_blank", "free_response"})
_CN_ORD = "一二三四五六七八九十"


def _rich_doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}] if text else [],
            }
        ],
    }


def _heading(text: str, level: int = 2) -> ExportHeadingNode:
    return ExportHeadingNode(level=level, content=_rich_doc(text))


def _rich_text(text: str) -> ExportRichTextNode:
    return ExportRichTextNode(content=_rich_doc(text))


def _cn_ordinal(index: int) -> str:
    """0-based → 一、二、…；超出十字用阿拉伯数字。"""
    if 0 <= index < len(_CN_ORD):
        return _CN_ORD[index]
    return str(index + 1)


def _format_score(score: float) -> str:
    return f"{score:g}"


def _type_display_name(item: ExamPaperItem) -> str:
    from app.services.paper_engine.snapshot import TYPE_NAMES
    return TYPE_NAMES.get(item.q_type,item.q_type)


def _inline_nodes_to_text(nodes: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for n in nodes:
        t = n.get("type")
        if t == "text":
            parts.append(str(n.get("text") or ""))
        elif t == "inlineMath":
            parts.append(str((n.get("attrs") or {}).get("latex") or ""))
        elif t == "hardBreak":
            parts.append("\n")
    return "".join(parts).strip()


def _answer_plain(answer: Any, options: list[ExportOption]) -> str:
    return _inline_nodes_to_text(answer_spec_to_inline(answer, options))


def _analysis_plain(analysis: Any) -> str:
    if not analysis:
        return ""
    if isinstance(analysis, str):
        return analysis.strip()
    if isinstance(analysis, dict):
        return rich_doc_to_plain_text(analysis).strip()
    return str(analysis).strip()


def _q_type(snap: dict[str, Any]) -> str:
    raw = snap.get("q_type") or ""
    if hasattr(raw, "value"):
        return str(raw.value)
    return str(raw)


def build_export_filename(
    title: str,
    mode: ExportMode,
    *,
    include_analysis: bool = False,
    when: Optional[datetime] = None,
) -> str:
    when = when or datetime.now()
    stamp = when.strftime("%Y%m%d%H%M")
    mode_label = "有答案" if mode == MODE_WITH_ANSWERS else "无答案"
    analysis_suffix = "_含解析" if (mode == MODE_WITH_ANSWERS and include_analysis) else ""
    safe = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (title or "").strip()) or "试卷"
    safe = safe.strip(" ._") or "试卷"
    return f"{safe}_{mode_label}{analysis_suffix}_{stamp}.docx"


class ExamPaperAssembler:
    """从试卷条目快照装配 CompositionExportDoc。"""

    def assemble(
        self,
        paper: ExamPaper,
        *,
        mode: ExportMode,
        include_analysis: bool = False,
    ) -> CompositionExportDoc:
        if mode not in (MODE_WITHOUT_ANSWERS, MODE_WITH_ANSWERS):
            raise ValueError(f"Unsupported export mode: {mode!r}")
        # 无答案卷强制不含解析，避免参数误传导致泄漏。
        if mode == MODE_WITHOUT_ANSWERS:
            include_analysis = False

        items = sorted(paper.items or [], key=lambda it: (it.seq, it.id))
        nodes: list[CompositionExportNode] = []
        nodes.extend(self._header_nodes(paper))

        numbered = self._number_items(paper, items)
        nodes.extend(self._body_nodes(paper, numbered, mode=mode))

        if mode == MODE_WITH_ANSWERS:
            nodes.append(ExportPageBreakNode())
            nodes.extend(
                self._answer_section_nodes(
                    paper, numbered, include_analysis=include_analysis
                )
            )

        return CompositionExportDoc(title=paper.title or "试卷", nodes=nodes)

    def _sections(self,part,items):
        types=list(dict.fromkeys(s["q_type"] for s in part.get("sections",[])))
        for item in items:
            if item.part_key==part["key"] and item.q_type not in types:types.append(item.q_type)
        return [{"q_type":t} for t in types]

    def _header_nodes(self, paper: ExamPaper) -> list[CompositionExportNode]:
        snap = paper.template_snapshot_json or {}
        template_name = str(snap.get("name") or "")
        lines = [
            f"实际总分：{_format_score(paper.actual_total_score)} 分",
            f"平行套别：第 {paper.set_index} 套",
        ]
        if template_name:
            lines.append(f"模板：{template_name}")
        if paper.duration_minutes:
            lines.append(f"时长：{paper.duration_minutes} 分钟")
        if paper.created_at:
            lines.append(f"出卷时间：{paper.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("姓名________  日期________")
        if paper.instructions:
            lines.append(f"注意事项：{paper.instructions}")

        return [
            _heading(paper.title or "试卷", level=1),
            _rich_text("\n".join(lines)),
        ]

    def _number_items(
        self, paper: ExamPaper, items: list[ExamPaperItem]
    ) -> list[tuple[int, ExamPaperItem]]:
        """按模板 part/section 顺序编号；孤儿条目追加在末尾。"""
        parts = (paper.template_snapshot_json or {}).get("parts") or []
        by_key: dict[tuple[str, int], list[ExamPaperItem]] = defaultdict(list)
        for it in items:
            by_key[(it.part_key, it.q_type)].append(it)

        ordered: list[ExamPaperItem] = []
        seen: set[int] = set()
        for part in parts:
            if not isinstance(part, dict):
                continue
            pkey = str(part.get("key") or "")
            for section in self._sections(part, items):
                if not isinstance(section, dict):
                    continue
                tid = section.get("q_type")
                if tid is None:
                    continue
                for it in by_key.get((pkey, str(tid)), []):
                    if it.id not in seen:
                        ordered.append(it)
                        seen.add(it.id)

        for it in items:
            if it.id not in seen:
                ordered.append(it)
                seen.add(it.id)

        return [(idx + 1, it) for idx, it in enumerate(ordered)]

    def _body_nodes(
        self,
        paper: ExamPaper,
        numbered: list[tuple[int, ExamPaperItem]],
        *,
        mode: ExportMode,
    ) -> list[CompositionExportNode]:
        del mode  # 正文装配与模式无关；答案永不内联进题干。
        parts = (paper.template_snapshot_json or {}).get("parts") or []
        by_key: dict[tuple[str, int], list[tuple[int, ExamPaperItem]]] = defaultdict(list)
        for num, it in numbered:
            by_key[(it.part_key, it.q_type)].append((num, it))

        nodes: list[CompositionExportNode] = []
        emitted: set[int] = set()

        for p_idx, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            pkey = str(part.get("key") or "")
            part_title = str(part.get("title") or pkey or f"部分{p_idx + 1}")
            part_items = [
                (n, it) for (k, _), group in by_key.items() if k == pkey for n, it in group
            ]
            # 保持模板 section 顺序重排
            ordered_part: list[tuple[int, ExamPaperItem]] = []
            for section in self._sections(part, [it for _,it in numbered]):
                if not isinstance(section, dict):
                    continue
                tid = section.get("q_type")
                if tid is None:
                    continue
                for n, it in by_key.get((pkey, str(tid)), []):
                    if it.id not in {x.id for _, x in ordered_part}:
                        ordered_part.append((n, it))
            if not ordered_part and not part_items:
                continue

            if not ordered_part:
                ordered_part = sorted(part_items, key=lambda x: x[0])

            part_score = sum(it.score for _, it in ordered_part)
            nodes.append(
                _heading(
                    f"第{_cn_ordinal(p_idx)}部分 {part_title}（共 {_format_score(part_score)} 分）",
                    level=2,
                )
            )

            # 按 section 输出大题标题
            section_idx = 0
            for section in self._sections(part, [it for _,it in numbered]):
                if not isinstance(section, dict):
                    continue
                tid = section.get("q_type")
                if tid is None:
                    continue
                group = [
                    (n, it)
                    for n, it in by_key.get((pkey, str(tid)), [])
                    if it.id not in emitted
                ]
                if not group:
                    continue
                type_name = _type_display_name(group[0][1])
                sec_score = sum(it.score for _, it in group)
                nodes.append(
                    _heading(
                        f"{_cn_ordinal(section_idx)}、{type_name}"
                        f"（共{len(group)}题，共 {_format_score(sec_score)} 分）",
                        level=3,
                    )
                )
                section_idx += 1
                for num, it in group:
                    nodes.extend(self._question_nodes(num, it))
                    emitted.add(it.id)

        # 未出现在模板结构中的条目
        leftovers = [(n, it) for n, it in numbered if it.id not in emitted]
        if leftovers:
            nodes.append(_heading("其他", level=2))
            for num, it in leftovers:
                nodes.extend(self._question_nodes(num, it))

        return nodes

    def _question_nodes(
        self, number: int, item: ExamPaperItem
    ) -> list[CompositionExportNode]:
        snap = item.content_snapshot_json or {}
        if not isinstance(snap, dict):
            snap = {}
        options = _parse_options(snap.get("options"))
        q_type = _q_type(snap)
        columns = _resolve_option_columns(options, None)

        nodes: list[CompositionExportNode] = [
            ExportQuestionNode(
                number=str(number),
                score=float(item.score),
                q_type=q_type,
                stem=snap.get("content"),
                options=options,
                option_columns=columns,
                # 题干区永不内联答案/解析（有答案卷答案集中在分页后的参考答案区）。
                answer=None,
                thinking=None,
                analysis=None,
                summary=None,
            )
        ]
        if q_type in _SUBJECTIVE_TYPES:
            nodes.append(ExportAnswerSpaceNode(lines=4, style="lined"))
        return nodes

    def _answer_section_nodes(
        self,
        paper: ExamPaper,
        numbered: list[tuple[int, ExamPaperItem]],
        *,
        include_analysis: bool,
    ) -> list[CompositionExportNode]:
        parts = (paper.template_snapshot_json or {}).get("parts") or []
        by_key: dict[tuple[str, int], list[tuple[int, ExamPaperItem]]] = defaultdict(list)
        for num, it in numbered:
            by_key[(it.part_key, it.q_type)].append((num, it))

        nodes: list[CompositionExportNode] = [_heading(ANSWER_SECTION_TITLE, level=1)]
        emitted: set[int] = set()

        for p_idx, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            pkey = str(part.get("key") or "")
            part_title = str(part.get("title") or pkey or f"部分{p_idx + 1}")
            part_groups: list[tuple[str, list[tuple[int, ExamPaperItem]]]] = []
            section_idx = 0
            for section in self._sections(part, [it for _,it in numbered]):
                if not isinstance(section, dict):
                    continue
                tid = section.get("q_type")
                if tid is None:
                    continue
                group = [
                    (n, it)
                    for n, it in by_key.get((pkey, str(tid)), [])
                    if it.id not in emitted
                ]
                if not group:
                    continue
                type_name = _type_display_name(group[0][1])
                part_groups.append(
                    (f"{_cn_ordinal(section_idx)}、{type_name}", group)
                )
                section_idx += 1
                for _, it in group:
                    emitted.add(it.id)

            if not part_groups:
                continue

            nodes.append(
                _heading(f"第{_cn_ordinal(p_idx)}部分 {part_title}", level=2)
            )
            for sec_label, group in part_groups:
                nodes.append(_heading(sec_label, level=3))
                nodes.extend(
                    self._format_answer_group(group, include_analysis=include_analysis)
                )

        leftovers = [(n, it) for n, it in numbered if it.id not in emitted]
        if leftovers:
            nodes.append(_heading("其他", level=2))
            nodes.extend(
                self._format_answer_group(leftovers, include_analysis=include_analysis)
            )
        return nodes

    def _format_answer_group(
        self,
        group: list[tuple[int, ExamPaperItem]],
        *,
        include_analysis: bool,
    ) -> list[CompositionExportNode]:
        objective_bits: list[str] = []
        nodes: list[CompositionExportNode] = []

        def flush_objective() -> None:
            nonlocal objective_bits
            if objective_bits:
                nodes.append(_rich_text("  ".join(objective_bits)))
                objective_bits = []

        for num, it in group:
            snap = it.content_snapshot_json or {}
            if not isinstance(snap, dict):
                snap = {}
            options = _parse_options(snap.get("options"))
            q_type = _q_type(snap)
            ans_text = _answer_plain(snap.get("answer"), options) or "（无）"

            if q_type in _OBJECTIVE_TYPES:
                objective_bits.append(f"{num}.{ans_text}")
            else:
                flush_objective()
                nodes.append(_rich_text(f"{num}.【参考答案】{ans_text}"))

            if include_analysis:
                analysis = _analysis_plain(snap.get("analysis"))
                if analysis:
                    flush_objective()
                    nodes.append(_rich_text(f"{num}.【解析】{analysis}"))

        flush_objective()
        return nodes
