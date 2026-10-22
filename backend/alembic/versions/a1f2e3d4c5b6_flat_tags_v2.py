"""Fixed answer types and flat tag paper rules; explicit legacy maintenance gate.

Revision ID: a1f2e3d4c5b6
Revises: f7a8b9c0d1e2
"""
from alembic import op
import sqlalchemy as sa

revision = "a1f2e3d4c5b6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    legacy = sum(conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar_one()
                 for t in ("paper_templates", "exam_papers", "exam_paper_batches", "exam_paper_items"))
    if legacy and not op.get_context().config.attributes.get("flat_tags_maintenance"):
        raise RuntimeError("旧模板需要维护升级：先备份并运行 scripts/upgrade_flat_tags.py --apply；应用未启动")
    # Phase 1: explicitly authorized legacy test-paper rebuild. Ordinary questions stay intact.
    if legacy:
        for table in ("exam_paper_items", "exam_papers", "exam_paper_batches", "paper_templates"):
            conn.execute(sa.text(f"DELETE FROM {table}"))
    # Phase 2: expand tag and template contracts.
    with op.batch_alter_table("tags") as b:
        b.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
        b.add_column(sa.Column("seed_key", sa.String(64), nullable=True))
        b.create_unique_constraint("uq_tag_subject_seed", ["subject_id", "seed_key"])
    op.create_index("ix_question_tags_tag_question", "question_tags", ["tag_id", "question_id"])
    with op.batch_alter_table("paper_templates") as b:
        b.add_column(sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"))
        b.alter_column("total_score", existing_type=sa.Float(), type_=sa.Numeric(10, 1), existing_nullable=False)
    op.create_table("paper_template_tag_refs",
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("paper_templates.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="RESTRICT"), primary_key=True))
    op.create_index("ix_paper_template_tag_refs_tag_id", "paper_template_tag_refs", ["tag_id"])
    with op.batch_alter_table("exam_papers") as b:
        b.alter_column("actual_total_score", existing_type=sa.Float(), type_=sa.Numeric(10, 1), existing_nullable=False)
    # Phase 3: remove obsolete directory constraints and snapshots.
    with op.batch_alter_table("exam_paper_items") as b:
        b.drop_constraint("fk_exam_paper_items_question_type_id_question_types", type_="foreignkey")
        b.drop_column("question_type_id")
        b.drop_column("question_type_path_snapshot")
        b.drop_column("category_snapshot_json")
        b.add_column(sa.Column("section_key", sa.String(64), nullable=False))
        b.add_column(sa.Column("q_type", sa.String(32), nullable=False))
        b.add_column(sa.Column("tag_snapshot_json", sa.JSON(), nullable=False))
        b.alter_column("score", existing_type=sa.Float(), type_=sa.Numeric(10, 1), existing_nullable=False)
    with op.batch_alter_table("questions") as b:
        b.drop_constraint("fk_questions_question_type_id_question_types", type_="foreignkey")
        b.drop_index("ix_questions_question_type_id")
        b.drop_column("question_type_id")
    for table in ("question_categories", "categories", "category_dimensions", "question_types"):
        op.drop_table(table)


def downgrade():
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT count(*) FROM paper_templates")).scalar_one():
        raise RuntimeError("v2 试卷数据不能自动降级；请恢复升级前备份")
    op.drop_table("paper_template_tag_refs")
    for table in ("exam_paper_items", "exam_papers", "exam_paper_batches", "paper_templates"):
        op.drop_table(table)
    op.drop_index("ix_question_tags_tag_question", table_name="question_tags")
    with op.batch_alter_table("tags") as b:
        b.drop_constraint("uq_tag_subject_seed", type_="unique")
        b.drop_column("enabled")
        b.drop_column("seed_key")
    # Reuse the immutable historical schema definition for empty-paper downgrade tests.
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name("f7a8b9c0d1e2_crcc_category_type_exam_paper.py")
    spec = importlib.util.spec_from_file_location("historical_crcc_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
