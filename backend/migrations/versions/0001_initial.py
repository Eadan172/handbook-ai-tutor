"""initial scope A schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    guid = sa.String(36)
    vector_type = sa.JSON()
    if is_pg:
        from pgvector.sqlalchemy import Vector

        vector_type = Vector(1536)

    op.create_table(
        "users",
        sa.Column("id", guid, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "courses",
        sa.Column("id", guid, primary_key=True),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "sources",
        sa.Column("id", guid, primary_key=True),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", guid, sa.ForeignKey("courses.id"), nullable=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "tasks",
        sa.Column("id", guid, primary_key=True),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("step", sa.String(128), nullable=False, server_default="queued"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("arq_job_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", guid, primary_key=True),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=True),
        sa.Column("end_time", sa.Float(), nullable=True),
        sa.Column("locator", sa.String(255), nullable=True),
        sa.Column("embedding", vector_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "source_summaries",
        sa.Column("id", guid, primary_key=True),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("outline_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("prompt_version", sa.String(64), nullable=False, server_default="summarize.v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "knowledge_points",
        sa.Column("id", guid, primary_key=True),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("key_terms_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("chunk_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("prompt_version", sa.String(64), nullable=False, server_default="extract_knowledge.v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "quizzes",
        sa.Column("id", guid, primary_key=True),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False, server_default="quiz_generate.v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "quiz_questions",
        sa.Column("id", guid, primary_key=True),
        sa.Column("quiz_id", guid, sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False),
        sa.Column("correct_index", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("chunk_ids_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "quiz_attempts",
        sa.Column("id", guid, primary_key=True),
        sa.Column("quiz_id", guid, sa.ForeignKey("quizzes.id"), nullable=False),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "tutor_messages",
        sa.Column("id", guid, primary_key=True),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "token_usages",
        sa.Column("id", guid, primary_key=True),
        sa.Column("user_id", guid, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("source_id", guid, sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_sources_user_id", "sources", ["user_id"])
    op.create_index("ix_document_chunks_source_id", "document_chunks", ["source_id"])
    op.create_index("ix_token_usages_task", "token_usages", ["task"])


def downgrade() -> None:
    for table in [
        "token_usages",
        "tutor_messages",
        "quiz_attempts",
        "quiz_questions",
        "quizzes",
        "knowledge_points",
        "source_summaries",
        "document_chunks",
        "tasks",
        "sources",
        "courses",
        "users",
    ]:
        op.drop_table(table)
