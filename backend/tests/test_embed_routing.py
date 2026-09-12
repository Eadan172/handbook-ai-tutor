"""Embeddings must never ride a chat-only default (DeepSeek / deepseek-chat)."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services.llm.models import looks_like_chat_model
from app.services.llm.openai_compatible import OpenAICompatibleProvider
from app.services.llm.router import EMBED_MISSING_MESSAGE, LLMConfigError, ModelRouter

VENDOR_KEYS = (
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "SILICONFLOW_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_COMPAT_API_KEY",
    "OPENAI_COMPAT_BASE_URL",
    "EMBED_API_BASE",
    "EMBED_API_KEY",
    "EMBED_MODEL",
    "LLM_PROVIDER_EMBED",
    "LLM_PROVIDER_TEXT",
    "LLM_TASK_ROUTES",
)


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _clear_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    for env in VENDOR_KEYS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "")
    monkeypatch.setenv("LLM_PROVIDER_EMBED", "")


def test_looks_like_chat_model_catches_deepseek_chat():
    assert looks_like_chat_model("deepseek-chat")
    assert looks_like_chat_model("Qwen/Qwen2.5-7B-Instruct")
    assert not looks_like_chat_model("BAAI/bge-m3")
    assert not looks_like_chat_model("text-embedding-v3")
    assert not looks_like_chat_model("text-embedding-3-small")


def test_deepseek_only_fails_loud_for_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_vendors(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek-key-0000000000")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "deepseek")
    get_settings.cache_clear()
    router = ModelRouter()
    assert router.default_name == "deepseek"
    with pytest.raises(LLMConfigError) as exc:
        router.provider_for("embed")
    message = str(exc.value)
    assert "LLM_PROVIDER_EMBED" in message
    assert "siliconflow" in message.lower() or "dashscope" in message.lower()
    assert "deepseek-chat" in message.lower() or "embeddings" in message.lower()


def test_deepseek_plus_siliconflow_routes_embed_to_bge(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_vendors(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek-key-0000000000")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test-siliconflow-key-0000")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "")
    get_settings.cache_clear()
    router = ModelRouter()
    assert router.default_name == "deepseek"
    provider = router.provider_for("embed")
    assert provider.name == "siliconflow"
    assert provider.model_for("embed") == "BAAI/bge-m3"
    assert provider.model_for("embed") != "deepseek-chat"
    assert "siliconflow.cn" in (getattr(provider, "base_url", "") or "")


def test_explicit_embed_deepseek_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_vendors(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek-key-0000000000")
    monkeypatch.setenv("LLM_PROVIDER_EMBED", "deepseek")
    get_settings.cache_clear()
    router = ModelRouter()
    with pytest.raises(LLMConfigError):
        router.provider_for("embed")


def test_mock_default_still_allows_mock_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_vendors(monkeypatch)
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "mock")
    get_settings.cache_clear()
    router = ModelRouter()
    provider = router.provider_for("embed")
    assert provider.name == "mock"
    assert provider.model_for("embed") == "mock-embed"


def test_openai_compat_base_url_does_not_hijack_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_vendors(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek-key-0000000000")
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "deepseek")
    get_settings.cache_clear()
    router = ModelRouter()
    chat = router.provider_for("summarize")
    assert chat.name == "deepseek"
    assert "deepseek.com" in (getattr(chat, "base_url", "") or "")
    assert "siliconflow" not in (getattr(chat, "base_url", "") or "")


@pytest.mark.asyncio
async def test_openai_compatible_refuses_chat_model_on_embeddings() -> None:
    provider = OpenAICompatibleProvider(
        name="deepseek",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-test",
        models={"default": "deepseek-chat"},
    )
    with pytest.raises(RuntimeError) as exc:
        await provider.embed(task="embed", texts=["hello"])
    assert "/embeddings" in str(exc.value)
    assert "deepseek-chat" in str(exc.value)


def test_describe_routes_marks_embed_unready_when_only_deepseek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_vendors(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-deepseek-key-0000000000")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "deepseek")
    get_settings.cache_clear()
    rows = {row["task"]: row for row in ModelRouter().describe_routes()}
    assert rows["embed"]["ready"] is False
    assert rows["summarize"]["ready"] is True
    assert EMBED_MISSING_MESSAGE[:12] in (rows["embed"]["error"] or "")
