"""组卷模板：分区 + 题型规则 + 扁平标签条件（JSON）。"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .base import Base


class PaperTemplate(Base):
    """组卷模板：分区 / 题型规则 / 扁平标签条件存于 parts_json。

    is_system_default 的模板不可删除，可「恢复出厂」；出卷时会快照到批次。
    """

    __tablename__ = "paper_templates"

    id = Column(Integer, primary_key=True, index=True)
    schema_version = Column(Integer, nullable=False, default=2, server_default="2")
    subject_id = Column(Integer, ForeignKey("subjects.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    total_score = Column(Numeric(10, 1), nullable=False)
    # [{key, title, part_score, sections:[{key, q_type, tag_filter, count, score_each}]}]
    parts_json = Column(JSON, nullable=False, default=list)
    # 全卷标签条件 {tag_ids, match}；出卷时可临时替换。
    scope_json = Column(JSON, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    instructions = Column(Text, nullable=True)
    is_system_default = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)
    seed_key = Column(String(64), nullable=True, index=True)

    created_by = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    subject = relationship("Subject", backref="paper_templates")
    creator = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        UniqueConstraint("subject_id", "name", name="uq_paper_template_subject_name"),
    )


class PaperTemplateTagRef(Base):
    __tablename__ = "paper_template_tag_refs"
    template_id = Column(Integer, ForeignKey("paper_templates.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True, index=True)
