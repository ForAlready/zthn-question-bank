"""crcc: category taxonomy, question type tree, paper templates, exam papers

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-19

一期二次开发结构变更:
  * category_dimensions / categories / question_categories
  * question_types + questions.question_type_id（可空，由种子/回填填充）
  * paper_templates
  * exam_paper_batches / exam_papers / exam_paper_items

不迁移 Tag→分类；不删除遗留 papers 表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "category_dimensions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("seed_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name=op.f("fk_category_dimensions_subject_id_subjects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_dimensions")),
        sa.UniqueConstraint("subject_id", "name", name="uq_category_dimension_subject_name"),
    )
    op.create_index(op.f("ix_category_dimensions_id"), "category_dimensions", ["id"])
    op.create_index(op.f("ix_category_dimensions_subject_id"), "category_dimensions", ["subject_id"])
    op.create_index(op.f("ix_category_dimensions_seed_key"), "category_dimensions", ["seed_key"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dimension_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("seed_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dimension_id"],
            ["category_dimensions.id"],
            name=op.f("fk_categories_dimension_id_category_dimensions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("dimension_id", "parent_id", "name", name="uq_category_dim_parent_name"),
    )
    op.create_index(op.f("ix_categories_id"), "categories", ["id"])
    op.create_index(op.f("ix_categories_dimension_id"), "categories", ["dimension_id"])
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"])
    op.create_index(op.f("ix_categories_seed_key"), "categories", ["seed_key"])

    op.create_table(
        "question_categories",
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name=op.f("fk_question_categories_question_id_questions")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], name=op.f("fk_question_categories_category_id_categories")
        ),
        sa.PrimaryKeyConstraint("question_id", "category_id", name=op.f("pk_question_categories")),
    )

    op.create_table(
        "question_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allows_children", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("selectable", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("legacy_key", sa.String(length=64), nullable=True),
        sa.Column("seed_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name=op.f("fk_question_types_subject_id_subjects")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["question_types.id"],
            name=op.f("fk_question_types_parent_id_question_types"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_types")),
        sa.UniqueConstraint(
            "subject_id", "parent_id", "name", name="uq_question_type_subject_parent_name"
        ),
    )
    op.create_index(op.f("ix_question_types_id"), "question_types", ["id"])
    op.create_index(op.f("ix_question_types_subject_id"), "question_types", ["subject_id"])
    op.create_index(op.f("ix_question_types_parent_id"), "question_types", ["parent_id"])
    op.create_index(op.f("ix_question_types_legacy_key"), "question_types", ["legacy_key"])
    op.create_index(op.f("ix_question_types_seed_key"), "question_types", ["seed_key"])

    op.add_column("questions", sa.Column("question_type_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_questions_question_type_id"), "questions", ["question_type_id"])
    op.create_foreign_key(
        op.f("fk_questions_question_type_id_question_types"),
        "questions",
        "question_types",
        ["question_type_id"],
        ["id"],
    )

    op.create_table(
        "paper_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("parts_json", sa.JSON(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("is_system_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("seed_key", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name=op.f("fk_paper_templates_subject_id_subjects")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name=op.f("fk_paper_templates_created_by_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_templates")),
        sa.UniqueConstraint("subject_id", "name", name="uq_paper_template_subject_name"),
    )
    op.create_index(op.f("ix_paper_templates_id"), "paper_templates", ["id"])
    op.create_index(op.f("ix_paper_templates_subject_id"), "paper_templates", ["subject_id"])
    op.create_index(op.f("ix_paper_templates_seed_key"), "paper_templates", ["seed_key"])

    op.create_table(
        "exam_paper_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("n_sets", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cross_set_dedup", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("template_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("seed", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name=op.f("fk_exam_paper_batches_subject_id_subjects")
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["paper_templates.id"],
            name=op.f("fk_exam_paper_batches_template_id_paper_templates"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name=op.f("fk_exam_paper_batches_created_by_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_paper_batches")),
    )
    op.create_index(op.f("ix_exam_paper_batches_id"), "exam_paper_batches", ["id"])
    op.create_index(op.f("ix_exam_paper_batches_subject_id"), "exam_paper_batches", ["subject_id"])
    op.create_index(op.f("ix_exam_paper_batches_template_id"), "exam_paper_batches", ["template_id"])
    op.create_index(op.f("ix_exam_paper_batches_created_by"), "exam_paper_batches", ["created_by"])

    op.create_table(
        "exam_papers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("set_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("template_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("actual_total_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("seed", sa.String(length=64), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_by", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["exam_paper_batches.id"],
            name=op.f("fk_exam_papers_batch_id_exam_paper_batches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"], name=op.f("fk_exam_papers_subject_id_subjects")
        ),
        sa.ForeignKeyConstraint(
            ["finalized_by"], ["user.id"], name=op.f("fk_exam_papers_finalized_by_user")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name=op.f("fk_exam_papers_created_by_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_papers")),
    )
    op.create_index(op.f("ix_exam_papers_id"), "exam_papers", ["id"])
    op.create_index(op.f("ix_exam_papers_batch_id"), "exam_papers", ["batch_id"])
    op.create_index(op.f("ix_exam_papers_subject_id"), "exam_papers", ["subject_id"])
    op.create_index(op.f("ix_exam_papers_created_by"), "exam_papers", ["created_by"])

    op.create_table(
        "exam_paper_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("part_key", sa.String(length=64), nullable=False),
        sa.Column("question_type_id", sa.Integer(), nullable=False),
        sa.Column("question_type_path_snapshot", sa.String(length=512), nullable=True),
        sa.Column("category_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("content_snapshot_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["exam_papers.id"],
            name=op.f("fk_exam_paper_items_paper_id_exam_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], name=op.f("fk_exam_paper_items_question_id_questions")
        ),
        sa.ForeignKeyConstraint(
            ["question_type_id"],
            ["question_types.id"],
            name=op.f("fk_exam_paper_items_question_type_id_question_types"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_paper_items")),
    )
    op.create_index(op.f("ix_exam_paper_items_id"), "exam_paper_items", ["id"])
    op.create_index(op.f("ix_exam_paper_items_paper_id"), "exam_paper_items", ["paper_id"])
    op.create_index(op.f("ix_exam_paper_items_question_id"), "exam_paper_items", ["question_id"])
    op.create_index("ix_exam_paper_items_paper_seq", "exam_paper_items", ["paper_id", "seq"])


def downgrade() -> None:
    op.drop_table("exam_paper_items")
    op.drop_table("exam_papers")
    op.drop_table("exam_paper_batches")
    op.drop_table("paper_templates")
    op.drop_constraint(op.f("fk_questions_question_type_id_question_types"), "questions", type_="foreignkey")
    op.drop_index(op.f("ix_questions_question_type_id"), table_name="questions")
    op.drop_column("questions", "question_type_id")
    op.drop_table("question_types")
    op.drop_table("question_categories")
    op.drop_table("categories")
    op.drop_table("category_dimensions")
