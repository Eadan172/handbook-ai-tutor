from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import GUID


class SourceSummary(Base):
    __tablename__ = "source_summaries"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("sources.id"), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    overview: Mapped[str] = mapped_column(Text)
    outline_json: Mapped[str] = mapped_column(Text, default="[]")
    prompt_version: Mapped[str] = mapped_column(String(64), default="summarize.v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[UUID] = mapped_column(GUID(), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(GUID(), ForeignKey("sources.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(Text)
    key_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    chunk_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    prompt_version: Mapped[str] = mapped_column(String(64), default="extract_knowledge.v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
