#!/usr/bin/env bash
# Bash twin of `start.bat`: bring up BOTH the API (8000) and the web UI (3000)
# in docker-less local mode, from one command.
#
# Use this when you are in a POSIX shell (Git Bash / WSL / CI) and want the same
# environment `start.bat` sets on Windows. On Windows the normal way to start the
# app is still to double-click `start.bat` — it opens two independent console
# windows that keep running after the terminal that launched them goes away.
#
# Usage:  bash scripts/run_local_all.sh [api_port] [web_port]
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd -W 2>/dev/null || pwd)"   # SQLite cannot open a POSIX "/e/..." path
API_PORT="${1:-8000}"
WEB_PORT="${2:-3000}"

PY="$ROOT/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/.venv/bin/python"
NODE="$(command -v node || echo /d/nodejs/node.exe)"

echo "project : $ROOT"
echo "api     : http://127.0.0.1:$API_PORT"
echo "web     : http://localhost:$WEB_PORT"
echo

# ---- API ---------------------------------------------------------------
# The root `.env` is the Docker template (postgres / redis / minio), so these
# overrides are what make the app talk to the local SQLite file instead.
# Deliberately NOT set: LOCAL_STORAGE_PATH (would pin the storage location and
# make /settings/llm read-only), LLM_DEFAULT_PROVIDER (would silently disable
# the real model, because a process env var beats `.env`) and STT_PROVIDER
# (leave to `.env`: mock | faster_whisper).
(
  cd "$ROOT/backend"
  if [ -d "$ROOT/tools/ffmpeg/bin" ]; then
    FFMPEG_BIN="$(cygpath -w "$ROOT/tools/ffmpeg/bin" 2>/dev/null || echo "$ROOT/tools/ffmpeg/bin")"
    export PATH="$FFMPEG_BIN:$PATH"
  fi
  DATABASE_URL="sqlite+aiosqlite:///$ROOT/backend/tutor.db" \
  DATABASE_URL_SYNC="sqlite:///$ROOT/backend/tutor.db" \
  TASK_BACKEND=inline \
  STORAGE_BACKEND=local \
  RAG_PROVIDER=pgvector \
  SECRET_KEY="dev-secret-change-me-use-at-least-32-bytes" \
  CORS_ORIGINS="http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT" \
  "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT"
) &

# ---- web ---------------------------------------------------------------
(
  cd "$ROOT/frontend"
  NEXT_PUBLIC_API_BASE_URL="http://localhost:$API_PORT" \
  "$NODE" node_modules/next/dist/bin/next start -p "$WEB_PORT"
) &

# ---- readiness ---------------------------------------------------------
for i in $(seq 1 60); do
  api=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/health" || true)
  web=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$WEB_PORT/login" || true)
  if [ "$api" = "200" ] && [ "$web" = "200" ]; then
    echo "[ready] api and web are both up -> http://localhost:$WEB_PORT"
    break
  fi
  sleep 1
  if [ "$i" = "60" ]; then
    echo "[warn] still not ready after 60s (api=$api web=$web) — check the output above"
  fi
done

wait
