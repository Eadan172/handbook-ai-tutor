"""End-to-end acceptance run for mp4 + PDF inputs.

Covers, for each material:
  1. upload + ingest until status=ready
  2. structured study notes (summary + knowledge + AI-generated notes)
  3. tutor Q&A "这个资料主要讲了什么"
  4. quiz generation + all-C submission + full explanations

Outputs are written under test-outputs/<kind>/ as JSON.

Run:  ./.venv/Scripts/python.exe scripts/e2e_acceptance.py
Requires the backend on http://127.0.0.1:8000 with ffmpeg on PATH.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
OUT = ROOT / "test-outputs"

EMAIL = "demo@example.com"
PASSWORD = "password123"

QUESTION = "这个资料主要讲了什么"


def login(client: httpx.Client) -> str:
    r = client.post(
        f"{API}/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    if r.status_code == 404:
        r = client.post(
            f"{API}/api/v1/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=30,
        )
    r.raise_for_status()
    return r.json()["access_token"]


def upload_and_wait(client: httpx.Client, token: str, path: Path, timeout_s: int = 2400) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    with path.open("rb") as fh:
        r = client.post(
            f"{API}/api/v1/sources/upload",
            headers=headers,
            files={"file": (path.name, fh)},
            timeout=300,
        )
    r.raise_for_status()
    source = r.json()
    sid = source["id"]
    print(f"[{path.name}] uploaded id={sid} kind={source.get('kind')}", flush=True)

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(f"{API}/api/v1/sources/{sid}", headers=headers, timeout=30)
        r.raise_for_status()
        s = r.json()
        status = s.get("status")
        if status == "ready":
            print(f"[{path.name}] ready", flush=True)
            return s
        if status == "failed":
            raise RuntimeError(f"ingest failed: {s.get('error_message')}")
        time.sleep(10)
    raise TimeoutError(f"ingest not ready within {timeout_s}s")


def collect(client: httpx.Client, token: str, source: dict, kind_dir: Path) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    sid = source["id"]
    kind_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"source": source}

    def get(path: str, name: str, timeout: int = 120):
        r = client.get(f"{API}{path}", headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        (kind_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    # 1. structured notes: summary + knowledge points + AI notes
    summary = get(f"/api/v1/sources/{sid}/summary", "01_summary.json")
    knowledge = get(f"/api/v1/sources/{sid}/knowledge", "02_knowledge.json")
    r = client.post(f"{API}/api/v1/sources/{sid}/notes/generate", headers=headers, timeout=600)
    r.raise_for_status()
    notes = r.json()
    (kind_dir / "03_notes.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    report["notes"] = {"summary_title": summary.get("title"), "knowledge_points": len(knowledge), "ai_notes": len(notes)}

    # 2. tutor Q&A
    r = client.post(
        f"{API}/api/v1/sources/{sid}/tutor/chat",
        headers=headers,
        json={"message": QUESTION},
        timeout=600,
    )
    r.raise_for_status()
    answer = r.json()
    qa = {"question": QUESTION, "answer": answer}
    (kind_dir / "04_tutor_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    report["tutor"] = {"citations": len(answer.get("citations") or [])}

    # 3. quiz: generate -> all-C submission -> explanations
    r = client.post(f"{API}/api/v1/sources/{sid}/quiz/generate", headers=headers, timeout=900)
    r.raise_for_status()
    quiz = r.json()
    (kind_dir / "05_quiz.json").write_text(json.dumps(quiz, ensure_ascii=False, indent=2), encoding="utf-8")

    answers = []
    for q in quiz["questions"]:
        if q["question_type"] == "choice" and q.get("options"):
            answers.append({"question_id": q["id"], "selected_index": min(2, len(q["options"]) - 1), "text_answer": None})
        else:
            answers.append({"question_id": q["id"], "selected_index": None, "text_answer": "C"})
    r = client.post(
        f"{API}/api/v1/quizzes/{quiz['id']}/attempt",
        headers=headers,
        json={"answers": answers},
        timeout=900,
    )
    r.raise_for_status()
    attempt = r.json()
    (kind_dir / "06_attempt_all_c.json").write_text(json.dumps(attempt, ensure_ascii=False, indent=2), encoding="utf-8")
    report["quiz"] = {
        "questions": len(quiz["questions"]),
        "graded": attempt.get("graded_count"),
        "score": attempt.get("score"),
    }
    return report


def main() -> int:
    mp4 = ROOT / "1_1 法语字母表.mp4"
    pdf = OUT / "inputs" / "photosynthesis.pdf"
    assert mp4.exists(), f"missing {mp4}"
    assert pdf.exists(), f"missing {pdf}"

    with httpx.Client() as client:
        token = login(client)
        reports = {}
        reports["pdf"] = collect(client, token, upload_and_wait(client, token, pdf), OUT / "pdf")
        reports["mp4"] = collect(client, token, upload_and_wait(client, token, mp4), OUT / "mp4")

    (OUT / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2), flush=True)
    print("E2E ACCEPTANCE PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
