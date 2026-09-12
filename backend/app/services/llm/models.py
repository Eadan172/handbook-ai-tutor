"""Shared model-name heuristics used by the router and HTTP providers."""
from __future__ import annotations

# Chat-only checkpoints must never be posted to /embeddings.
_CHAT_MODEL_MARKERS = (
    "chat",
    "instruct",
    "turbo",
    "haiku",
    "sonnet",
    "opus",
    "plus",
    "vl-",
)


def looks_like_chat_model(model: str | None) -> bool:
    """True for dialogue checkpoints that vendors reject on /embeddings."""
    name = (model or "").strip().lower()
    if not name:
        return False
    if "embed" in name:
        return False
    return any(marker in name for marker in _CHAT_MODEL_MARKERS)
