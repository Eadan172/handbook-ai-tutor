# Handbook AI Tutor — Scope A

Upload a **PDF** or **MP4** → async parse / STT → chunk → embed → RAG with citations → auto summary + knowledge points → quiz → Socratic tutor grounded in sources.

This repository implements **Scope A only** (strict minimum closed loop). Phase 2/3 items (EPUB/DOCX/PPTX, Flashcards/FSRS, knowledge graph, multi-agent, Prometheus/Grafana, teacher/org, learner memory L1–L3) are explicitly deferred.

## Quick start (Docker Compose)

```bash
cp .env.example .env
# Leave LLM_DEFAULT_PROVIDER=mock for a fully offline demo (no API keys).
docker compose up --build
```

Then open:

- App: http://localhost:3000
- API: http://localhost:8000/docs
- MinIO console: http://localhost:9001 (`minioadmin` / `minioadmin`)

Register in the UI → upload any PDF / short MP4 → wait until status is `ready` → open Summary, Tutor, and Quiz.

Optional reverse proxy: `docker compose --profile with-nginx up --build` then http://localhost:8080

## Local / docker-less (this is what CI and Cloud Agents use)

Postgres, Redis, and MinIO are **not** required. The API falls back to SQLite, filesystem storage, an in-process task runner, MockLLM, and MockSTT.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "./backend[dev]"

export DATABASE_URL=sqlite+aiosqlite:///./tutor.db
export TASK_BACKEND=inline
export STORAGE_BACKEND=local
export LOCAL_STORAGE_PATH=./data/storage
export LLM_DEFAULT_PROVIDER=mock
export STT_PROVIDER=mock
export RAG_PROVIDER=pgvector
export SECRET_KEY=dev-secret
export CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
export NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
```

Generate demo files (writes to `test-outputs/inputs/`):

```bash
python scripts/generate_samples.py
```

## Switch Mock → real providers

Business code only passes `task="summarize" | extract_knowledge | quiz_generate | tutor | segment_summarize | embed`. Model names live in `backend/config/providers.yaml`.

1. Put vendor keys in **`.env` only** (never the frontend, git, or the database):

   ```
   DASHSCOPE_API_KEY=...
   DEEPSEEK_API_KEY=...
   SILICONFLOW_API_KEY=...
   OPENAI_API_KEY=...
   ANTHROPIC_API_KEY=...
   ```

2. Point tasks at a provider in `backend/config/providers.yaml`:

   ```yaml
   default_provider: dashscope
   task_routes:
     summarize: dashscope
     extract_knowledge: dashscope
     quiz_generate: dashscope
     tutor: deepseek
     segment_summarize: dashscope
     embed: siliconflow
   ```

3. Set `LLM_DEFAULT_PROVIDER=dashscope` (or `deepseek` / `siliconflow` / `openai` / `ollama`).

China-first defaults (DashScope / DeepSeek / SiliconFlow) are already in the YAML. Overseas OpenAI/Anthropic traffic uses process env `HTTP_PROXY` / `HTTPS_PROXY` — **never hardcode a proxy**.

Tests and CI must keep `LLM_DEFAULT_PROVIDER=mock`.

Optional local models: `OLLAMA_BASE_URL=http://127.0.0.1:11434` and `task_routes.*.: ollama`.

Optional real STT: `STT_PROVIDER=faster_whisper` and `pip install -e "./backend[stt]"` (needs CPU/GPU weights; MockSTT is the default).

### Local video pipeline (ffmpeg + faster-whisper, offline)

The mp4 pipeline extracts audio with **ffmpeg** and transcribes locally with
**faster-whisper** — no API key, audio never leaves the machine.

1. **ffmpeg** — download a Windows static build and place it at
   `tools/ffmpeg/bin/ffmpeg.exe` (the `tools/` dir is git-ignored). Both
   `start.bat` and `scripts/run_local_*.sh` auto-inject it into `PATH`.
   Linux/macOS: just install ffmpeg via your package manager.
2. **Model weights** — set `STT_WHISPER_MODEL=base|small` in `.env`. If
   HuggingFace is unreachable, download from ModelScope into
   `tools/whisper-<size>/` (`model.bin`, `config.json`, `tokenizer.json`,
   `vocabulary.txt`); the STT layer picks the local dir up automatically.
   `base` ≈ 145 MB and runs fine on ~4 GB free RAM; `small` ≈ 484 MB, better
   Chinese quality, needs more memory. Long videos are transcribed in
   5-minute chunks to cap peak memory.
3. `.env`: `STT_PROVIDER=faster_whisper`, `STT_WHISPER_VAD=true` (skips
   silence between sentences in lectures).

Mixed-language lectures (e.g. Chinese teaching with French/English read-aloud)
work out of the box — Whisper auto-detects language per segment, no fine-tuning
needed.

## Smoke tests

```bash
cd backend
LLM_DEFAULT_PROVIDER=mock TASK_BACKEND=inline STORAGE_BACKEND=local \
  pytest -q tests/test_auth.py tests/test_upload.py tests/test_rag.py tests/test_quiz.py
```

These cover: JWT register/login, upload enqueue + PDF pipeline, RAG retrieve (mock embeddings), quiz generate/attempt (MockLLM). No vendor APIs are called.

## End-to-end acceptance (real LLM + real STT)

`scripts/e2e_acceptance.py` uploads a PDF and an MP4, waits for ingest, then
collects summary / knowledge points / AI notes / a tutor Q&A
("这个资料主要讲了什么") / a quiz submitted with all-C answers plus full
explanations into `test-outputs/<kind>/` (git-ignored — LLM output about your
own materials stays local):

```bash
# backend must be running:  bash scripts/run_local_backend.sh
./.venv/Scripts/python.exe scripts/e2e_acceptance.py
```

## Layout

```
backend/app/{api,core,domain,services,models,repositories,workers,prompts,utils}
backend/migrations, tests, pyproject.toml
frontend/          Next.js + React + TS + Tailwind + shadcn/ui + TanStack Query + Zustand
infrastructure/{docker,nginx,postgres,redis,minio}
scripts/, docs/
docker-compose.yml, .env.example, README.md
```

## Architecture (Scope A)

- **Auth**: JWT access tokens, bcrypt passwords.
- **Upload**: PDF/MP4 → MinIO (or local disk) → `Task` row → ARQ job (or inline asyncio).
- **Progress**: task row + Redis pub/sub; SSE at `GET /api/v1/tasks/{id}/events` (UI also polls).
- **PDF**: pypdf → page-aware chunks.
- **Video**: FFmpeg audio extract → MockSTT (or Faster-Whisper) → timestamped segments → **map-reduce** (retry per window; never dump the full transcript into one LLM call).
- **Embeddings**: Mock (hash vector) or OpenAI-compatible `/embeddings`.
- **RAG**: `RAGProvider` interface; `LlamaIndexRAGProvider` + `PgVectorRAGProvider`. Citations include PDF page or video timestamps, plus `source_id` / `chunk_id`.
- **LLM**: `LLMProvider` + `ModelRouter`. Every call writes `TokenUsage`.
- **Tutor**: Socratic prompt, retrieval tools/services only — no SQL from the agent.

## Known gaps (out of Scope A)

- EPUB / DOCX / PPTX parsers
- Flashcards / FSRS (`app/domain/flashcards.py` placeholder)
- Knowledge graph, multi-agent orchestration
- Prometheus / Grafana
- Teacher / organization accounts
- Learner memory L1–L3 (`app/domain/mastery.py` placeholder)
- SSE `EventSource` cannot send `Authorization`; the UI polls task status instead
- Anthropic embeddings are not provided by the vendor API (chat works; embed falls back)
- Faster-Whisper is optional and not installed in the default image

## Suggested next slice after Scope A

1. Real DashScope/SiliconFlow embeddings + pgvector HNSW in production Compose.
2. Flashcards + FSRS on knowledge points.
3. Persistent tutor session + learner memory L1 (recap of last session).
4. Teacher/org tenant and shared course libraries.
