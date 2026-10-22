"""考试试卷 Word 导出：装配 + 复用组稿 docx 渲染器。"""

from __future__ import annotations

from app.models.exam_paper import ExamPaper
from app.services.exporting.exam_paper_assemble import (
    ExamPaperAssembler,
    build_export_filename,
)
from app.services.exporting.exam_paper_contracts import (
    MODE_WITH_ANSWERS,
    ExamPaperExportResult,
    ExportMode,
)
from app.services.exporting.renderers.composition_docx import CompositionDocxRenderer


def export_exam_paper_docx(
    paper: ExamPaper,
    *,
    mode: ExportMode,
    include_analysis: bool = False,
) -> ExamPaperExportResult:
    """生成试卷 docx 临时文件。

    with_answers 时在试题正文后插入真正的 page break，再输出「参考答案」。
    include_analysis 仅在 with_answers 时生效；默认 False。
    """
    if mode != MODE_WITH_ANSWERS:
        include_analysis = False

    doc = ExamPaperAssembler().assemble(
        paper, mode=mode, include_analysis=include_analysis
    )
    path = CompositionDocxRenderer().render(doc)
    filename = build_export_filename(
        paper.title or doc.title, mode, include_analysis=include_analysis
    )
    return ExamPaperExportResult(path=path, filename=filename)
