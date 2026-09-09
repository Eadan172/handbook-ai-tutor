from fastapi import APIRouter

from app.api import auth, knowledge, quiz, sources, tasks, tutor

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(sources.router)
api_router.include_router(tasks.router)
api_router.include_router(knowledge.router)
api_router.include_router(quiz.router)
api_router.include_router(tutor.router)
