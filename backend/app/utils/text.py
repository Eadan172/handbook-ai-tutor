from __future__ import annotations

import unicodedata


_MOJIBAKE_MARKERS = (
    "锛",
    "銆",
    "鈥",
    "鈺",
    "妯",
    "璺",
    "璇",
    "鐨",
    "绔",
    "馃",
    "浣",
    "鍙",
    "Ã",
    "Â",
    "â€",
    "ï¿½",
    "\ufffd",
)


def _mojibake_score(value: str) -> int:
    return sum(value.count(marker) for marker in _MOJIBAKE_MARKERS)


def normalise_text(value: str) -> str:
    """Return NFC text and conservatively undo common double-decoding.

    UTF-8 decoded as GB18030 is a frequent Windows/Chinese deployment failure;
    UTF-8 decoded as Latin-1 is common in proxies. A repair is accepted only
    when it strictly reduces known mojibake markers, so normal multilingual text
    is left untouched.
    """
    current = unicodedata.normalize("NFC", str(value or ""))
    current_score = _mojibake_score(current)
    if current_score == 0:
        return current

    candidates = [current]
    for mistaken_encoding in ("gb18030", "latin1"):
        try:
            candidate = current.encode(mistaken_encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        candidates.append(unicodedata.normalize("NFC", candidate))

    best = min(candidates, key=_mojibake_score)
    return best if _mojibake_score(best) < current_score else current


__all__ = ["normalise_text"]
