.PHONY: test backend frontend compose samples

test:
	cd backend && LLM_DEFAULT_PROVIDER=mock TASK_BACKEND=inline STORAGE_BACKEND=local pytest -q

backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm run dev

compose:
	docker compose up --build

samples:
	python scripts/generate_samples.py
