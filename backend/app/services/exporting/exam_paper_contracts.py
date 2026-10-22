"""考试试卷导出契约：模式常量与结果类型。

装配结果复用组稿的 CompositionExportDoc，以便直接走 CompositionDocxRenderer。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExportMode = Literal["without_answers", "with_answers"]

MODE_WITHOUT_ANSWERS: ExportMode = "without_answers"
MODE_WITH_ANSWERS: ExportMode = "with_answers"

ANSWER_SECTION_TITLE = "参考答案"


@dataclass(frozen=True)
class ExamPaperExportResult:
    """渲染后的临时文件路径与建议下载文件名。"""

    path: str
    filename: str
