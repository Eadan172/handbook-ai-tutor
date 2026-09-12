from fastapi import APIRouter

from app.api import auth, knowledge, llm, notes, quiz, sources, system, tasks, tutor, usage

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(llm.router)
api_router.include_router(system.router)
api_router.include_router(sources.router)
api_router.include_router(tasks.router)
api_router.include_router(knowledge.router)
api_router.include_router(notes.router)
api_router.include_router(quiz.router)
api_router.include_router(tutor.router)
api_router.include_router(usage.router)
