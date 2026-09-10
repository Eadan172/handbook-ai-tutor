"""User-editable runtime paths, persisted inside the project.

Two locations used to be frozen at process start: where uploads are written
(`LOCAL_STORAGE_PATH`) and which `providers.yaml` governs LLM routing
(`PROVIDERS_CONFIG_PATH`). Changing either meant editing `.env` and restarting.

This module lets the settings page move them at runtime. A browser cannot
safely rewrite `.env` (it holds API keys and comments), so the overrides live in
a separate small JSON file:

    backend/config/runtime.json

Resolution order, highest first:

  1. a real process environment variable (docker compose, CI export, start.bat)
     -> never touched, the UI reports it as locked
  2. runtime.json written by the settings page
  3. .env values
  4. the pre-generated project-folder default below

Keeping (1) on top is deliberate: a container that pins LOCAL_STORAGE_PATH must
not be silently re-pointed by a click in a browser.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR, REPO_ROOT, env_var_is_external, get_settings

logger = logging.getLogger("app.paths")

# Settings field -> environment variable that carries it.
OVERRIDABLE: dict[str, str] = {
    "local_storage_path": "LOCAL_STORAGE_PATH",
    "providers_config_path": "PROVIDERS_CONFIG_PATH",
}

#: Human-facing metadata, kept next to the routing table so the API, the tests
#: and the UI agree on what each entry means.
PATHS_META: dict[str, dict[str, str]] = {
    "local_storage_path": {
        "label": "上传文件存储目录",
        "kind": "directory",
        "hint": "电子书、视频与图片原件存放处。改到新目录后，已上传的旧文件不会被搬移。",
    },
    "providers_config_path": {
        "label": "LLM 供应商配置文件",
        "kind": "file",
        "hint": "providers.yaml 决定每个任务调用哪个供应商与模型。必须是一个能解析出 providers 段的 YAML 文件。",
    },
}

OVERRIDES_FILE = BACKEND_DIR / "config" / "runtime.json"


# ---------------------------------------------------------------- defaults


def project_defaults() -> dict[str, str]:
    """The pre-generated, absolute, inside-the-project locations.

    Always computable without reading any config file, so the app is usable out
    of the box and the UI has something concrete to pre-fill.
    """
    return {
        "local_storage_path": str((REPO_ROOT / "data" / "storage").resolve()),
        "providers_config_path": str((BACKEND_DIR / "config" / "providers.yaml").resolve()),
    }


# ---------------------------------------------------------------- overrides


def load_overrides() -> dict[str, str]:
    """Read runtime.json. Never raises: a corrupt file must not stop boot."""
    if not OVERRIDES_FILE.exists():
        return {}
    try:
        with OVERRIDES_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring unreadable %s: %s", OVERRIDES_FILE, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("ignoring %s: expected a JSON object", OVERRIDES_FILE)
        return {}
    return {
        key: str(value)
        for key, value in data.items()
        if key in OVERRIDABLE and isinstance(value, str) and value.strip()
    }


def save_overrides(overrides: dict[str, str]) -> None:
    """Write runtime.json atomically so a crash mid-write cannot corrupt it."""
    payload = {
        key: str(value).strip()
        for key, value in overrides.items()
        if key in OVERRIDABLE and str(value).strip()
    }
    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OVERRIDES_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, OVERRIDES_FILE)


def apply_overrides() -> dict[str, str]:
    """Push runtime.json into os.environ and drop the settings cache.

    Returns the overrides that were actually applied (externally pinned entries
    are skipped). Safe to call on every boot and after every save.
    """
    overrides = load_overrides()
    applied: dict[str, str] = {}
    for field, env_name in OVERRIDABLE.items():
        if env_var_is_external(env_name):
            logger.debug("%s is pinned by the process environment; override skipped", env_name)
            continue
        value = overrides.get(field)
        if value:
            os.environ[env_name] = value
            applied[field] = value
        else:
            # Drop a stale override so .env / the code default takes over again.
            os.environ.pop(env_name, None)
    get_settings.cache_clear()
    return applied


# ---------------------------------------------------------------- inspection


def _dir_stats(path: Path) -> dict[str, Any]:
    """Cheap size accounting, for "am I about to orphan my uploads?" decisions."""
    files = 0
    total = 0
    if path.is_dir():
        try:
            for child in path.rglob("*"):
                if child.is_file():
                    files += 1
                    try:
                        total += child.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
    return {"files": files, "bytes": total}


def _yaml_summary(path: Path) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    if not isinstance(config, dict) or not isinstance(config.get("providers"), dict):
        raise ValueError("YAML 里没有 providers 段，不能作为供应商配置使用")
    return {
        "providers": sorted(config["providers"]),
        "default_provider": config.get("default_provider"),
    }


def describe_paths() -> dict[str, Any]:
    """Everything the settings page needs to render the two path fields."""
    settings = get_settings()
    defaults = project_defaults()
    overrides = load_overrides()
    current: dict[str, Any] = {}
    for field, env_name in OVERRIDABLE.items():
        value = str(getattr(settings, field) or "")
        pinned = env_var_is_external(env_name)
        if pinned:
            source = "env"
        elif overrides.get(field):
            source = "custom"
        else:
            source = "default"

        path = Path(value)
        entry: dict[str, Any] = {
            **PATHS_META[field],
            "key": field,
            "env_var": env_name,
            "current": value,
            "default": defaults[field],
            "custom_value": overrides.get(field),
            "source": source,
            "locked_by_env": pinned,
            "exists": path.is_file() if PATHS_META[field]["kind"] == "file" else path.is_dir(),
            "note": None,
            "detail": {},
        }
        if field == "local_storage_path" and settings.storage_backend != "local":
            # Don't let the page imply a local folder matters when uploads actually
            # go to object storage.
            entry["note"] = (
                f"当前 STORAGE_BACKEND={settings.storage_backend}，上传的文件进的是对象存储，"
                "这个本地目录不会被使用；切回 local 后才会生效。"
            )
        try:
            if PATHS_META[field]["kind"] == "directory":
                entry["detail"] = _dir_stats(path) if path.is_dir() else {"files": 0, "bytes": 0}
            elif path.is_file():
                entry["detail"] = _yaml_summary(path)
        except Exception as exc:  # diagnostics only — never fail the whole page
            entry["detail"] = {"error": f"{type(exc).__name__}: {exc}"}

        current[field] = entry
    return {
        "paths": list(current.values()),
        "overrides_file": str(OVERRIDES_FILE),
        "overrides": overrides,
        "overrides_applied": {
            field: str(getattr(settings, field) or "") for field in OVERRIDABLE
        },
    }
