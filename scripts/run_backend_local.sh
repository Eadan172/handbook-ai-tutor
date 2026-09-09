#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$ROOT/tutor.db}"
export TASK_BACKEND="${TASK_BACKEND:-inline}"
export STORAGE_BACKEND="${STORAGE_BACKEND:-local}"
export LOCAL_STORAGE_PATH="${LOCAL_STORAGE_PATH:-$ROOT/data/storage}"
export LLM_DEFAULT_PROVIDER="${LLM_DEFAULT_PROVIDER:-mock}"
export STT_PROVIDER="${STT_PROVIDER:-mock}"
export RAG_PROVIDER="${RAG_PROVIDER:-pgvector}"
export SECRET_KEY="${SECRET_KEY:-dev-secret-change-me-use-at-least-32-bytes}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"
export PYTHONPATH="$ROOT/backend"
cd "$ROOT/backend"
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
