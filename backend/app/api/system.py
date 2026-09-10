"""Runtime path management — where uploads go, which providers.yaml is used.

Read-only visibility lives in /health; this router is the write side that backs
the "路径设置" card on /settings/llm. Every change is validated, persisted to
`backend/config/runtime.json`, and applied to the running process immediately
(no restart), because both settings are read through `get_settings()` per call.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.config import BACKEND_DIR, REPO_ROOT, env_var_is_external, get_settings
from app.core.deps import get_current_user
from app.core.runtime_paths import (
    OVERRIDABLE,
    PATHS_META,
    apply_overrides,
    describe_paths,
    load_overrides,
    project_defaults,
    save_overrides,
)
from app.models.user import User
from app.services.storage import reset_storage

logger = logging.getLogger("app.paths")

router = APIRouter(prefix="/api/v1/system", tags=["system"])


class PathsIn(BaseModel):
    """Only the keys present are touched; null / "" restores the default.

    `extra="allow"` so an unexpected key produces our own explanatory 400 instead
    of a bare pydantic 422.
    """

    model_config = ConfigDict(extra="allow")

    local_storage_path: str | None = None
    providers_config_path: str | None = None


class PathsOut(BaseModel):
    paths: list[dict[str, Any]]
    overrides_file: str
    overrides: dict[str, str]
    overrides_applied: dict[str, str]
    changed: list[str] = []
    warnings: list[str] = []
    restart_required: bool = False


def _reject(message: str, *, field: str) -> HTTPException:
    return HTTPException(status_code=400, detail=f"{PATHS_META[field]['label']}：{message}")


def _check_common(path: Path, field: str) -> None:
    if not path.is_absolute():
        raise _reject("请填写绝对路径（例如 E:\\tutor-data\\storage）。", field=field)
    if path == path.anchor or path.parent == path:
        raise _reject("不能把磁盘根目录当作存储位置。", field=field)
    if path in {REPO_ROOT, BACKEND_DIR} or path in REPO_ROOT.parents:
        raise _reject(
            "该路径会覆盖项目自身目录，请选一个项目文件夹之外的独立目录。", field=field
        )


def _validate_directory(raw: str, field: str) -> str:
    path = Path(raw).expanduser()
    _check_common(path, field)
    if path.exists() and not path.is_dir():
        raise _reject(f"{path} 已经是一个文件，不能作为目录使用。", field=field)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise _reject(f"无法创建目录 {path}（{exc}）。", field=field) from exc
    probe = path / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise _reject(f"目录 {path} 不可写（{exc}）。", field=field) from exc
    return str(path.resolve())


def _validate_providers_config(raw: str, field: str) -> str:
    path = Path(raw).expanduser()
    _check_common(path, field)
    if not path.is_file():
        raise _reject(f"{path} 不是一个存在的文件。", field=field)
    try:
        with path.open("r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
    except Exception as exc:
        raise _reject(f"无法解析 YAML（{type(exc).__name__}: {exc}）。", field=field) from exc
    if not isinstance(config, dict) or not isinstance(config.get("providers"), dict):
        raise _reject("文件里没有 providers 段，不能作为供应商配置使用。", field=field)
    if "mock" not in config["providers"]:
        raise _reject("文件里必须至少定义 mock 供应商作为兜底。", field=field)
    return str(path.resolve())


_VALIDATORS: dict[str, Callable[[str, str], str]] = {
    "local_storage_path": _validate_directory,
    "providers_config_path": _validate_providers_config,
}


def _stored_names(root: Path) -> set[str]:
    """Relative names of everything already stored, for orphaning warnings."""
    if not root.is_dir():
        return set()
    try:
        return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    except OSError:
        return set()


@router.get("/paths", response_model=PathsOut, response_model_exclude_none=True)
async def get_paths(user: User = Depends(get_current_user)) -> PathsOut:
    """Current vs project-default location for each configurable path."""
    return PathsOut(**describe_paths())


@router.put("/paths", response_model=PathsOut, response_model_exclude_none=True)
async def update_paths(
    payload: PathsIn, user: User = Depends(get_current_user)
) -> PathsOut:
    """Validate, persist and hot-apply new locations.

    `null` (or an empty string) means "go back to the project default". Omitting
    a field leaves it alone.
    """
    submitted = payload.model_dump(exclude_unset=True)
    if not submitted:
        raise HTTPException(status_code=400, detail="没有需要修改的路径。")

    unknown = [k for k in submitted if k not in OVERRIDABLE]
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支持的路径字段：{', '.join(unknown)}")

    defaults = {k: str(Path(v).resolve()) for k, v in project_defaults().items()}
    settings_before = get_settings()
    before_effective = {k: str(getattr(settings_before, k) or "") for k in OVERRIDABLE}
    before_root = Path(before_effective["local_storage_path"])
    before_names = _stored_names(before_root) if "local_storage_path" in submitted else set()

    changed: list[str] = []
    overrides = load_overrides()

    for field, value in submitted.items():
        env_name = OVERRIDABLE[field]
        if env_var_is_external(env_name):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{PATHS_META[field]['label']} 由进程环境变量 {env_name} 固定，"
                    "页面改动不会生效。请修改启动脚本或 docker compose 后重启。"
                ),
            )
        raw = (value or "").strip()
        if not raw:
            overrides.pop(field, None)  # back to the project default
        else:
            resolved = _VALIDATORS[field](raw, field)
            if resolved == defaults[field]:
                overrides.pop(field, None)  # same as default -> don't store noise
            else:
                overrides[field] = resolved
        changed.append(field)

    save_overrides(overrides)
    applied = apply_overrides()
    settings = get_settings()

    warnings: list[str] = []
    # Only talk about a path that actually moved. Re-applying the same value is a
    # legitimate no-op, and claiming "switched" would be misleading.
    moved = {f for f in changed if str(getattr(settings, f) or "") != before_effective[f]}

    if "local_storage_path" in moved:
        # LocalStorage caches its root, so swap the instance out.
        reset_storage()
        new_root = Path(str(settings.local_storage_path)).resolve()
        if before_names and not _stored_names(new_root):
            warnings.append(
                f"新目录 {new_root} 目前是空的，而原目录 {before_root} 里还有 "
                f"{len(before_names)} 个文件。这些历史文件不会被搬移，"
                "对应条目的「原文件」将无法打开 —— 需要的话请手动复制过去。"
            )
        warnings.append("存储目录已切换：新上传写入新目录，已有文件保持原位。")
    elif "local_storage_path" in changed:
        warnings.append(f"存储目录未变化（仍为 {settings.local_storage_path}）。")

    if "providers_config_path" in moved:
        warnings.append(
            f"LLM 路由配置已切换到 {settings.providers_config_path}，下一个请求即生效（无需重启）。"
        )
    elif "providers_config_path" in changed:
        warnings.append(f"LLM 路由配置未变化（仍为 {settings.providers_config_path}）。")

    result = describe_paths()
    result.update(
        {
            "changed": sorted(set(changed)),
            "warnings": warnings,
            "restart_required": False,
        }
    )
    logger.info(
        "runtime paths updated by user=%s changed=%s applied=%s",
        user.id,
        sorted(set(changed)),
        applied,
    )
    return PathsOut(**result)
