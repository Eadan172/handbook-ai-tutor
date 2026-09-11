#!/usr/bin/env python
"""Fetch the ONNX recognition models used by the local (offline) OCR engine.

The Chinese+English model ships inside `rapidocr-onnxruntime`. Other languages are
~10 MB ONNX files published by the RapidAI team; this script downloads them once
into `backend/models/ocr/`, where `app.services.ocr` looks for them.

Usage:
    python scripts/fetch_ocr_models.py                 # every extra language
    python scripts/fetch_ocr_models.py --lang japan    # just one
    python scripts/fetch_ocr_models.py --list          # show availability
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
MODEL_DIR = BACKEND_DIR / "models" / "ocr"
MODELSCOPE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.5.0/onnx/PP-OCRv4/rec"

MODELS: dict[str, str] = {
    "japan": "japan_PP-OCRv4_rec_infer.onnx",
    "korean": "korean_PP-OCRv4_rec_infer.onnx",
    "latin": "latin_PP-OCRv3_rec_infer.onnx",
    "cyrillic": "cyrillic_PP-OCRv3_rec_infer.onnx",
    "chinese_cht": "chinese_cht_PP-OCRv3_rec_infer.onnx",
    "arabic": "arabic_PP-OCRv4_rec_infer.onnx",
    "devanagari": "devanagari_PP-OCRv4_rec_infer.onnx",
}


def fetch(lang: str) -> bool:
    filename = MODELS[lang]
    target = MODEL_DIR / filename
    if target.exists():
        print(f"  [skip] {lang:12s} already present ({target.stat().st_size / 1e6:.1f} MB)")
        return True
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{MODELSCOPE}/{filename}"
    tmp = target.with_suffix(target.suffix + ".part")
    print(f"  [get ] {lang:12s} {url}")
    try:
        with urllib.request.urlopen(url, timeout=300) as response:  # noqa: S310 (fixed host)
            tmp.write_bytes(response.read())
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        print(f"  [fail] {lang}: {type(exc).__name__}: {exc}")
        return False
    tmp.replace(target)
    print(f"  [ ok ] {lang:12s} -> {target} ({target.stat().st_size / 1e6:.1f} MB)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", action="append", choices=sorted(MODELS), help="language to fetch")
    parser.add_argument("--list", action="store_true", help="show what is available locally")
    args = parser.parse_args()

    if args.list:
        print(f"OCR model directory: {MODEL_DIR}")
        print("  ch / en      bundled with rapidocr-onnxruntime")
        for lang, filename in sorted(MODELS.items()):
            present = (MODEL_DIR / filename).exists()
            print(f"  {lang:12s} {'present' if present else 'missing'}")
        return 0

    langs = args.lang or sorted(MODELS)
    print(f"Fetching OCR recognition models into {MODEL_DIR}")
    ok = all(fetch(lang) for lang in langs)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
