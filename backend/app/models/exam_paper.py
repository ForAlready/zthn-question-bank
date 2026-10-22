"""考试试卷域：批次、试卷、条目（含内容快照）。与遗留 papers 表独立。"""
from datetime import datetime
import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Numeric,
)
from sqlalchemy.orm import relationship

from .base import Base


class ExamPaperStatus(str, enum.Enum):
    DRAFT = "draft"   # 可改分 / 换题 / 重抽
    FINAL = "final"   # 定稿后锁定内容与分值


class ExamPaperBatch(Base):
    """平行卷批次：一次 generate 产出 N 套，共享模板快照与去重集合。"""

    __tablename__ = "exam_paper_batches"

    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("paper_templates.id"), nullable=False, index=True)
    n_sets = Column(Integer, nullable=False, default=1)
    # True 时批次内各套题目互斥（AC-04）。
    cross_set_dedup = Column(Boolean, nullable=False, default=True)
    scope_json = Column(JSON, nullable=True)
    # 出卷瞬间的模板结构拷贝；后续改模板不影响已出批次。
    template_snapshot_json = Column(JSON, nullable=False)
    seed = Column(String(64), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    subject = relationship("Subject")
    template = relationship("PaperTemplate")
    creator = relationship("User", foreign_keys=[created_by])
    papers = relationship(
        "ExamPaper",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="ExamPaper.set_index",
    )


class ExamPaper(Base):
    """单套试卷（属于某一批次）。"""

    __tablename__ = "exam_papers"

    @property
    def template_warnings(self):
        """汇总条目快照中的模板偏离提示（换题后可能产生）。"""
        return list(dict.fromkeys(w for item in self.items
                    for w in (item.content_snapshot_json or {}).get("_template_warnings", [])))

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(
        Integer, ForeignKey("exam_paper_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    set_index = Column(Integer, nullable=False, default=1)  # 批次内套别，从 1 起
    status = Column(String(20), nullable=False, default=ExamPaperStatus.DRAFT.value)
    template_snapshot_json = Column(JSON, nullable=False)
    # 条目分值之和；改分后重算，可与模板 total_score 偏离。
    actual_total_score = Column(Numeric(10, 1), nullable=False, default=0)
    duration_minutes = Column(Integer, nullable=True)
    instructions = Column(Text, nullable=True)
    seed = Column(String(64), nullable=True)
    finalized_at = Column(DateTime, nullable=True)
    finalized_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    batch = relationship("ExamPaperBatch", back_populates="papers")
    subject = relationship("Subject")
    creator = relationship("User", foreign_keys=[created_by])
    finalizer = relationship("User", foreign_keys=[finalized_by])
    items = relationship(
        "ExamPaperItem",
        back_populates="paper",
        cascade="all, delete-orphan",
        order_by="ExamPaperItem.seq",
    )


class ExamPaperItem(Base):
    """试卷题目条目：分值与内容快照属于条目，不回写题库。

    定稿后依赖 content_snapshot_json 导出；题库后续改题不影响已定稿卷。
    """

    __tablename__ = "exam_paper_items"

    id = Column(Integer, primary_key=True, index=True)
    paper_id = Column(
        Integer, ForeignKey("exam_papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    part_key = Column(String(64), nullable=False)  # 对应模板分区 key
    section_key = Column(String(64), nullable=False)
    q_type = Column(String(32), nullable=False)
    tag_snapshot_json = Column(JSON, nullable=False, default=list)
    seq = Column(Integer, nullable=False)  # 卷内题号顺序
    score = Column(Numeric(10, 1), nullable=False)  # 本条目分值（可逐题改分）
    # 题干/选项/答案等拷贝；可含 _template_warnings 元数据。
    content_snapshot_json = Column(JSON, nullable=False)

    paper = relationship("ExamPaper", back_populates="items")
    question = relationship("Question")

    __table_args__ = (
        Index("ix_exam_paper_items_paper_seq", "paper_id", "seq"),
    )
