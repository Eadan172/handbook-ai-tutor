from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BACKEND_DIR, get_settings
from app.models.usage import TokenUsage
from app.services.llm.anthropic import AnthropicProvider
from app.services.llm.base import ChatMessage, EmbedResult, LLMProvider, LLMResult
from app.services.llm.mock import MockProvider
from app.services.llm.ollama import OllamaProvider
from app.services.llm.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger("app.llm")


class LLMConfigError(RuntimeError):
    """Raised when routing cannot be resolved to a usable provider.

    Deliberately loud: silently falling back to MockLLM hides a broken API key
    or a bad provider name behind plausible-looking fake results.
    """


# task -> modality. Text tasks read/write language; audio tasks consume
# transcripts of speech; vision tasks read pixels; embed produces vectors.
TEXT_TASKS = {
    "summarize",
    "extract_knowledge",
    "quiz_generate",
    "quiz_explain",
    "tutor",
    "notes_generate",
}
AUDIO_TASKS = {"segment_summarize"}
EMBED_TASKS = {"embed"}
VISION_TASKS = {"transcribe_image"}

MODALITY_ENV = {
    "text": "LLM_PROVIDER_TEXT",
    "audio": "LLM_PROVIDER_AUDIO",
    "embed": "LLM_PROVIDER_EMBED",
    "vision": "LLM_PROVIDER_VISION",
}

#: The Embedding API filled in on the settings page. It lives outside
#: providers.yaml because it is entered at runtime, and it is registered as a
#: synthetic provider spec so readiness checks and the diagnostics table treat
#: it exactly like a vendor from the file.
EMBED_OVERRIDE_NAME = "embed_override"
EMBED_OVERRIDE_ENV = {
    "base": "EMBED_API_BASE",
    "key": "EMBED_API_KEY",
    "model": "EMBED_MODEL",
}

# Order used by auto-detection when no provider is pinned explicitly.
AUTO_ORDER = ("dashscope", "deepseek", "siliconflow", "openai", "anthropic")

# Providers that can read images, best-first. DeepSeek has no vision model, so it
# is deliberately absent: an OCR call must never land on it by accident.
VISION_AUTO_ORDER = ("dashscope", "openai", "siliconflow", "anthropic", "ollama")

# Obvious placeholders that must not count as "a key was configured".
_PLACEHOLDER_KEYS = {"-", "none", "null", "changeme", "your-key", "your_api_key", "xxx", "todo"}
_MIN_KEY_LEN = 8


def _usable_key(value: str | None) -> bool:
    raw = (value or "").strip()
    if len(raw) < _MIN_KEY_LEN:
        return False
    return raw.lower() not in _PLACEHOLDER_KEYS


def modality_for(task: str) -> str:
    if task in EMBED_TASKS:
        return "embed"
    if task in AUDIO_TASKS:
        return "audio"
    if task in VISION_TASKS:
        return "vision"
    return "text"


class ModelRouter:
    """Routes task="..." to a configured provider. Records TokenUsage on every call.

    Resolution order (first hit wins):
      1. env LLM_TASK_ROUTES (JSON map, task -> provider)
      2. providers.yaml  task_routes[task]
      3. env LLM_PROVIDER_TEXT / LLM_PROVIDER_AUDIO / LLM_PROVIDER_EMBED by modality
      4. env LLM_DEFAULT_PROVIDER
      5. providers.yaml  default_provider
      6. "mock"
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.config = self._load_config()
        #: Specs that do not come from providers.yaml. Registered before the
        #: providers are built so every lookup below sees them like any vendor.
        self._synthetic_specs: dict[str, dict] = {}
        self._register_embed_override()
        self.providers = self._build_providers()
        self.task_routes: dict[str, str] = {
            str(k): str(v) for k, v in (self.config.get("task_routes") or {}).items()
        }
        self.env_task_routes = self._load_env_task_routes()
        # Empty LLM_DEFAULT_PROVIDER means "auto": use a vendor whose key is
        # actually present, instead of silently answering with MockLLM.
        self.default_name = (
            (self.settings.llm_default_provider or "").strip()
            or (self.config.get("default_provider") or "").strip()
            or "mock"
        )
        self.auto_detected = False
        self.embed_note: str | None = None
        if self.default_name == "mock" and not (self.settings.llm_default_provider or "").strip():
            detected = self._first_provider_with_key()
            if detected:
                self.default_name = detected
                self.auto_detected = True
                logger.info(
                    "LLM_DEFAULT_PROVIDER is unset; auto-selected %r because its API key is present",
                    detected,
                )

    @property
    def settings_path(self) -> str:
        return str(self._resolve_config_path())

    # ---------- config loading ----------

    def _resolve_config_path(self) -> Path:
        """Prefer the configured path, but never degrade to mock just because it is wrong.

        .env.example ships PROVIDERS_CONFIG_PATH=/app/config/providers.yaml, which
        only exists inside Docker. Locally that used to make every task fall back
        to MockLLM with no warning. A blank value (the documented local setting)
        must also mean "use the bundled file" — `Path("")` is `.`, which exists,
        so an unguarded `configured.is_file()` would try to open a directory.
        """
        raw = (self.settings.providers_config_path or "").strip()
        configured = Path(raw)
        if raw and configured.is_file():
            return configured
        bundled = BACKEND_DIR / "config" / "providers.yaml"
        if bundled.is_file():
            if raw:
                logger.warning(
                    "PROVIDERS_CONFIG_PATH=%s is not a file; falling back to the bundled %s",
                    raw,
                    bundled,
                )
            return bundled
        return configured

    def _load_config(self) -> dict:
        path = self._resolve_config_path()
        if not path.exists():
            logger.warning("providers config not found at %s; only mock is available", path)
            return {"default_provider": "mock", "task_routes": {}, "providers": {"mock": {"type": "mock"}}}
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    def _first_provider_with_key(self) -> str | None:
        specs = self.config.get("providers") or {}
        for name in AUTO_ORDER:
            spec = specs.get(name) or {}
            key_env = spec.get("api_key_env") or ""
            if key_env and _usable_key(os.environ.get(key_env)):
                return name
        return None

    def _has_embed_model(self, name: str) -> bool:
        if name == "mock":
            return True
        spec = self._spec_for(name)
        models = spec.get("models") or {}
        return bool(models.get("embed"))

    def _first_provider_with_embed(self) -> str | None:
        specs = self.config.get("providers") or {}
        for name in AUTO_ORDER:
            spec = specs.get(name) or {}
            key_env = spec.get("api_key_env") or ""
            if not key_env or not _usable_key(os.environ.get(key_env)):
                continue
            if (spec.get("models") or {}).get("embed"):
                return name
        return None

    def _first_provider_with_vision(self) -> str | None:
        """First keyed provider that declares a `transcribe_image` model."""
        specs = self.config.get("providers") or {}
        for name in VISION_AUTO_ORDER:
            spec = specs.get(name) or {}
            if not (spec.get("models") or {}).get("transcribe_image"):
                continue
            key_env = spec.get("api_key_env") or ""
            if spec.get("type") == "ollama" or not key_env:
                continue
            if _usable_key(os.environ.get(key_env)):
                return name
        return None

    def _load_env_task_routes(self) -> dict[str, str]:
        raw = (self.settings.llm_task_routes or "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM_TASK_ROUTES is not valid JSON, ignoring: %r", raw[:200])
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _register_embed_override(self) -> None:
        """Turn the settings-page Embedding API into a provider spec.

        Only registered when both an address and a model are present: half a
        configuration would route embeddings at a URL that cannot answer, which
        is worse than falling back to mock. A blank key is allowed on purpose —
        a locally hosted embeddings server usually has no auth.
        """
        base = (os.environ.get(EMBED_OVERRIDE_ENV["base"]) or "").strip()
        model = (os.environ.get(EMBED_OVERRIDE_ENV["model"]) or "").strip()
        if not base or not model:
            return
        spec: dict = {
            "type": "openai_compatible",
            "base_url": base,
            "models": {"default": model, "embed": model},
            "source": "settings",
        }
        if (os.environ.get(EMBED_OVERRIDE_ENV["key"]) or "").strip():
            spec["api_key_env"] = EMBED_OVERRIDE_ENV["key"]
        self._synthetic_specs[EMBED_OVERRIDE_NAME] = spec

    def _build_providers(self) -> dict[str, LLMProvider]:
        built: dict[str, LLMProvider] = {"mock": MockProvider()}
        specs = {**(self.config.get("providers") or {}), **self._synthetic_specs}
        for name, spec in specs.items():
            spec = spec or {}
            ptype = spec.get("type", "mock")
            models = spec.get("models") or {}
            if ptype == "mock":
                built[name] = MockProvider(
                    model=models.get("default", "mock-llm"),
                    embed_model=models.get("embed", "mock-embed"),
                )
            elif ptype == "openai_compatible":
                key_env = spec.get("api_key_env") or ""
                api_key = os.environ.get(key_env, "") if key_env else ""
                base_url = os.environ.get("OPENAI_COMPAT_BASE_URL") or spec.get("base_url") or ""
                if name == "openai_compat" and os.environ.get("OPENAI_COMPAT_MODEL"):
                    models = {**models, "default": os.environ["OPENAI_COMPAT_MODEL"]}
                built[name] = OpenAICompatibleProvider(
                    name=name,
                    base_url=base_url,
                    api_key=api_key,
                    models=models,
                )
            elif ptype == "ollama":
                base = os.environ.get("OLLAMA_BASE_URL") or spec.get("base_url") or "http://127.0.0.1:11434"
                built[name] = OllamaProvider(base_url=base, models=models)
            elif ptype == "anthropic":
                key_env = spec.get("api_key_env") or "ANTHROPIC_API_KEY"
                built[name] = AnthropicProvider(
                    name=name,
                    base_url=spec.get("base_url") or "https://api.anthropic.com",
                    api_key=os.environ.get(key_env, ""),
                    models=models,
                )
        return built

    # ---------- resolution ----------

    def provider_name_for(self, task: str) -> str:
        if task in self.env_task_routes:
            return self.env_task_routes[task]
        if task in self.task_routes:
            return self.task_routes[task]
        modality = modality_for(task)
        env_value = getattr(self.settings, f"llm_provider_{modality}", "") or ""
        if env_value.strip():
            return env_value.strip()
        if modality == "vision":
            # An OCR call must never inherit a text-only default: DeepSeek has no
            # vision model, so borrowing it would fail at request time with a
            # confusing vendor error. Only reuse the default when it can actually
            # see, else find a real vision provider — and say so loudly when there
            # is none, because the offline OCR engine is the other way out.
            default_provider = self.providers.get(self.default_name)
            if default_provider is not None and default_provider.supports_vision():
                return self.default_name
            discovered = self._first_provider_with_vision()
            if discovered:
                return discovered
            raise LLMConfigError(
                'No vision-capable provider is configured for task="transcribe_image". '
                f'"{self.default_name}" cannot read images. Either install the offline '
                "engine (pip install rapidocr-onnxruntime, then OCR_PROVIDER=rapidocr / "
                "auto), or add a vision key (e.g. DASHSCOPE_API_KEY) and set "
                "LLM_PROVIDER_VISION=dashscope."
            )
        return self.default_name

    def provider_for(self, task: str) -> LLMProvider:
        name = self.provider_name_for(task)
        if modality_for(task) == "embed" and (
            EMBED_OVERRIDE_NAME in self.providers or not self._has_embed_model(name)
        ):
            name = self._resolve_embed_provider(name)
        provider = self.providers.get(name)
        if provider is None:
            known = ", ".join(sorted(self.providers))
            raise LLMConfigError(
                f'LLM provider "{name}" (task="{task}") is not defined in '
                f"{self._resolve_config_path()}. Known providers: {known}."
            )
        self._validate_ready(name, task)
        return provider

    def _resolve_embed_provider(self, requested: str) -> str:
        """Embeddings degrade gracefully, with a visible note.

        Most chat vendors (DeepSeek) expose no /embeddings endpoint. Failing the
        whole ingest over that would be worse than falling back, so we walk:
        the Embedding API entered in 设置 -> explicit LLM_PROVIDER_EMBED -> any
        keyed provider with an embed model -> local deterministic vectors. The
        chosen name lands in the task message.
        """
        if EMBED_OVERRIDE_NAME in self.providers:
            # An explicit, hand-entered endpoint outranks auto-detection: the
            # person configured it precisely because they wanted it used.
            self.embed_note = "embeddings via the Embedding API configured in 设置"
            return EMBED_OVERRIDE_NAME
        explicit = (self.settings.llm_provider_embed or "").strip()
        if explicit and self.providers.get(explicit) and self._has_embed_model(explicit):
            self.embed_note = None
            return explicit
        candidate = self._first_provider_with_embed()
        if candidate:
            logger.warning(
                "provider %r has no embed model; using %r for embeddings", requested, candidate
            )
            self.embed_note = f"{requested} has no embed model; embeddings via {candidate}"
            return candidate
        logger.warning(
            "no provider with an embed model is configured; falling back to local mock embeddings"
        )
        self.embed_note = "no embed-capable provider configured; using local mock embeddings"
        return "mock"

    def _spec_for(self, name: str) -> dict:
        if name == "mock":
            return {}
        if name in self._synthetic_specs:
            return self._synthetic_specs[name]
        return ((self.config.get("providers") or {}).get(name) or {})

    def _validate_ready(self, name: str, task: str) -> None:
        if name == "mock":
            return
        spec = self._spec_for(name)
        if spec.get("type") == "ollama":
            return
        key_env = spec.get("api_key_env") or ""
        if key_env and not _usable_key(os.environ.get(key_env)):
            raise LLMConfigError(
                f'Provider "{name}" is selected for task="{task}" but {key_env} is missing or '
                f"still a placeholder. Put a real key in .env ({key_env}=...) or set "
                f"{MODALITY_ENV.get(modality_for(task), 'LLM_DEFAULT_PROVIDER')}=mock for offline mode."
            )
        models = spec.get("models") or {}
        if not models.get("default") and not models.get(task):
            raise LLMConfigError(
                f'Provider "{name}" has no model configured for task="{task}".'
            )

    # ---------- diagnostics ----------

    def describe_routes(self) -> list[dict]:
        """Human-readable view of what each task will actually call."""
        rows: list[dict] = []
        for task in sorted(TEXT_TASKS | AUDIO_TASKS | EMBED_TASKS | VISION_TASKS):
            modality = modality_for(task)
            try:
                name = self.provider_name_for(task)
                if modality == "embed" and (
                    EMBED_OVERRIDE_NAME in self.providers or not self._has_embed_model(name)
                ):
                    self.embed_note = None
                    name = self._resolve_embed_provider(name)
                provider = self.providers.get(name)
                if provider is None:
                    raise LLMConfigError(f'provider "{name}" is not defined in providers.yaml')
                self._validate_ready(name, task)
                spec = self._spec_for(name)
                key_env = spec.get("api_key_env") or ""
                rows.append(
                    {
                        "task": task,
                        "modality": modality,
                        "provider": name,
                        "model": provider.model_for(task),
                        "base_url": getattr(provider, "base_url", None),
                        "api_key_env": key_env or None,
                        "api_key_present": _usable_key(os.environ.get(key_env)) if key_env else None,
                        "ready": True,
                        "error": None,
                        "note": self.embed_note if modality == "embed" else None,
                    }
                )
            except LLMConfigError as exc:
                # provider_name_for can itself raise (a modality with no usable
                # provider at all). Never let that turn diagnostics into a 500.
                try:
                    fallback_name: str | None = self.provider_name_for(task)
                except LLMConfigError:
                    fallback_name = None
                rows.append(
                    {
                        "task": task,
                        "modality": modality,
                        "provider": fallback_name or "unavailable",
                        "model": None,
                        "base_url": None,
                        "api_key_env": None,
                        "api_key_present": None,
                        "ready": False,
                        "error": str(exc),
                        "note": None,
                    }
                )
        return rows

    # ---------- calls ----------

    async def complete(
        self,
        *,
        task: str,
        messages: list[ChatMessage] | list[dict],
        json_mode: bool = True,
        user_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> LLMResult:
        normalized: list[ChatMessage] = [
            m if isinstance(m, ChatMessage) else ChatMessage.model_validate(m) for m in messages
        ]
        provider = self.provider_for(task)
        result = await provider.complete(task=task, messages=normalized, json_mode=json_mode)
        logger.info(
            "llm task=%s provider=%s model=%s prompt_tokens=%s completion_tokens=%s",
            task,
            result.provider,
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
        )
        await self._record(task, result, user_id=user_id, source_id=source_id)
        return result

    async def embed(
        self,
        *,
        task: str = "embed",
        texts: list[str],
        user_id: UUID | None = None,
        source_id: UUID | None = None,
    ) -> EmbedResult:
        provider = self.provider_for(task)
        result = await provider.embed(task=task, texts=texts)
        logger.info(
            "llm task=%s provider=%s model=%s vectors=%s",
            task,
            result.provider,
            result.model,
            len(result.vectors),
        )
        await self._record(
            task,
            LLMResult(
                content="",
                prompt_tokens=result.prompt_tokens,
                completion_tokens=0,
                provider=result.provider,
                model=result.model,
            ),
            user_id=user_id,
            source_id=source_id,
        )
        return result

    async def _record(
        self,
        task: str,
        result: LLMResult,
        *,
        user_id: UUID | None,
        source_id: UUID | None,
    ) -> None:
        if self.session is None:
            return
        self.session.add(
            TokenUsage(
                user_id=user_id,
                source_id=source_id,
                task=task,
                provider=result.provider,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
        )
        await self.session.flush()
