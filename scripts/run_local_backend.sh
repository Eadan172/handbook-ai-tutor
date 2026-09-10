#!/usr/bin/env bash
# Start the API in docker-less mode, with exactly the environment `start.bat`
# uses on Windows.
#
# Why this file exists: the root `.env` is the *Docker* template
# (postgres / redis / minio), so running `uvicorn app.main:app` on its own makes
# the app try to reach `postgres:5432` and every request 500s. The overrides
# below are what make it talk to the local SQLite file instead.
#
# Deliberately NOT set here, for the same reasons `start.bat` leaves them out:
#   * LOCAL_STORAGE_PATH  -- a process env var would PIN the storage location and
#                            make the /settings/llm field read-only.
#   * LLM_DEFAULT_PROVIDER / LLM_PROVIDER_* -- process env beats `.env`, so
#                            pinning "mock" would silently disable the real LLM.
#   * OCR_PROVIDER / OCR_LANG -- leave to config defaults / `.env`.
#   * STT_PROVIDER -- leave to `.env` (mock | faster_whisper) so the video
#                            pipeline can be switched without editing this script.
#
# Usage:  bash scripts/run_local_backend.sh [port]
set -euo pipefail

# `pwd -W` gives a Windows path ("E:/...") under Git Bash. SQLite cannot open a
# POSIX path such as "/e/WorkBuddy/...", so the conversion matters.
cd "$(dirname "$0")/.."
ROOT="$(pwd -W 2>/dev/null || pwd)"
PORT="${1:-8000}"
PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/.venv/bin/python"

export DATABASE_URL="sqlite+aiosqlite:///$ROOT/backend/tutor.db"
export DATABASE_URL_SYNC="sqlite:///$ROOT/backend/tutor.db"
export TASK_BACKEND="inline"
export STORAGE_BACKEND="local"
export RAG_PROVIDER="pgvector"
export SECRET_KEY="dev-secret-change-me-use-at-least-32-bytes"
export CORS_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"

# ffmpeg for the mp4 pipeline (audio extraction). Downloaded on demand into
# tools/ffmpeg by the maintainer; harmless when absent. Windows process PATH
# lookup requires backslash form (cygpath -w) — "E:/..." entries are ignored.
if [ -d "$ROOT/tools/ffmpeg/bin" ]; then
  FFMPEG_BIN="$(cygpath -w "$ROOT/tools/ffmpeg/bin" 2>/dev/null || echo "$ROOT/tools/ffmpeg/bin")"
  export PATH="$FFMPEG_BIN:$PATH"
fi

cd "$ROOT/backend"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
