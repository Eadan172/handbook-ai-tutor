from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = _JSON_FENCE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"Could not parse JSON from LLM output: {text[:240]}")


def parse_model(text: str, model: type[T]) -> T:
    data = parse_json_object(text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"LLM JSON failed schema {model.__name__}: {exc}") from exc
