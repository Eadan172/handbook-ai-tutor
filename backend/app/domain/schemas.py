from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceOut(BaseModel):
    id: UUID
    filename: str
    content_type: str
    kind: str
    status: str
    title: str | None
    byte_size: int
    created_at: datetime
    task_id: UUID | None = None

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: UUID
    source_id: UUID
    kind: str
    status: str
    progress: int
    step: str
    message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class Citation(BaseModel):
    chunk_id: UUID
    source_id: UUID
    locator: str | None = None
    page_number: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    quote: str
    score: float | None = None


class KnowledgePointOut(BaseModel):
    id: UUID
    title: str
    summary: str
    key_terms: list[str]
    chunk_ids: list[UUID]

    model_config = {"from_attributes": True}


class SummaryOut(BaseModel):
    source_id: UUID
    title: str
    overview: str
    outline: list[str]
    prompt_version: str


class QuizQuestionPublic(BaseModel):
    id: UUID
    ordinal: int
    question: str
    options: list[str]


class QuizOut(BaseModel):
    id: UUID
    source_id: UUID
    title: str
    questions: list[QuizQuestionPublic]


class QuizAnswer(BaseModel):
    question_id: UUID
    selected_index: int


class QuizAttemptRequest(BaseModel):
    answers: list[QuizAnswer]


class QuizQuestionResult(BaseModel):
    question_id: UUID
    selected_index: int
    correct_index: int
    correct: bool
    explanation: str
    chunk_ids: list[UUID]


class QuizAttemptOut(BaseModel):
    id: UUID
    quiz_id: UUID
    score: float
    passed: bool
    results: list[QuizQuestionResult]


class TutorChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class TutorMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    citations: list[Citation]
    created_at: datetime


class RetrieveRequest(BaseModel):
    query: str
    source_id: UUID | None = None
    top_k: int = 5


class RetrieveResponse(BaseModel):
    citations: list[Citation]
