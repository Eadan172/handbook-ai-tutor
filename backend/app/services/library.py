from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunk import DocumentChunk
from app.models.knowledge import KnowledgePoint, SourceSummary
from app.models.note import SourceNote
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.source import Source
from app.models.task import Task
from app.models.tutor import TutorMessage
from app.models.usage import TokenUsage
from app.services.storage import StorageProvider

logger = logging.getLogger("app.library")


@dataclass
class DeleteReport:
    source_id: UUID
    filename: str
    storage_key: str
    storage_deleted: bool
    storage_error: str | None = None
    rows_deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total_rows(self) -> int:
        return sum(self.rows_deleted.values())


async def delete_source_cascade(
    session: AsyncSession,
    *,
    source: Source,
    storage: StorageProvider,
    delete_files: bool = True,
) -> DeleteReport:
    """Delete a source and every row that references it, plus the stored file.

    Order matters: children first, then the source row, then the blob. If the
    blob removal fails we still keep the DB consistent and report the error
    instead of rolling everything back (a stale file is harmless; a half
    deleted library is not).
    """
    report = DeleteReport(
        source_id=source.id,
        filename=source.filename,
        storage_key=source.storage_key,
        storage_deleted=False,
    )

    quiz_ids = (
        (await session.execute(select(Quiz.id).where(Quiz.source_id == source.id))).scalars().all()
    )

    # Leaf tables keyed by quiz
    if quiz_ids:
        report.rows_deleted["quiz_attempts"] = (
            await session.execute(delete(QuizAttempt).where(QuizAttempt.quiz_id.in_(quiz_ids)))
        ).rowcount or 0
        report.rows_deleted["quiz_questions"] = (
            await session.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids)))
        ).rowcount or 0
        report.rows_deleted["quizzes"] = (
            await session.execute(delete(Quiz).where(Quiz.id.in_(quiz_ids)))
        ).rowcount or 0

    for table, condition in (
        (DocumentChunk, DocumentChunk.source_id == source.id),
        (SourceSummary, SourceSummary.source_id == source.id),
        (KnowledgePoint, KnowledgePoint.source_id == source.id),
        (SourceNote, SourceNote.source_id == source.id),
        (TutorMessage, TutorMessage.source_id == source.id),
        (Task, Task.source_id == source.id),
        (TokenUsage, TokenUsage.source_id == source.id),
    ):
        result = await session.execute(delete(table).where(condition))
        if result.rowcount:
            report.rows_deleted[table.__tablename__] = result.rowcount

    await session.delete(source)
    report.rows_deleted["sources"] = 1
    await session.commit()

    if delete_files:
        try:
            report.storage_deleted = await storage.delete_bytes(source.storage_key)
        except Exception as exc:  # never fail the request because of a blob
            report.storage_error = f"{type(exc).__name__}: {exc}"
            logger.warning("failed to delete stored object %s: %s", source.storage_key, exc)

    return report
