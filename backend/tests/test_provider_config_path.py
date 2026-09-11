"""`PROVIDERS_CONFIG_PATH` resolution must never break routing.

Two shapes were shipped by the template and both used to be foot-guns:

  * `.env.example` says "leave BLANK for local runs". Passing "" straight to
    `Path()` gives `.`, which *exists* — the loader then tried to open a
    directory and every route died with
    `PermissionError: [Errno 13] Permission denied: '.'`.
  * The Docker value `/app/config/providers.yaml` does not exist locally.

Both must end up on the bundled `backend/config/providers.yaml`, and a genuinely
custom path must still be honoured.
"""
from __future__ import annotations

import pytest
import yaml

from app.core.config import BACKEND_DIR, get_settings
from app.services.llm.router import ModelRouter

BUNDLED = BACKEND_DIR / "config" / "providers.yaml"


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _router_for(path_value: str, monkeypatch) -> ModelRouter:
    monkeypatch.setenv("PROVIDERS_CONFIG_PATH", path_value)
    get_settings.cache_clear()
    return ModelRouter()


@pytest.mark.parametrize("value", ["", "   ", "/app/config/providers.yaml", "./nope.yaml"])
def test_unusable_path_falls_back_to_bundled(value, monkeypatch):
    router = _router_for(value, monkeypatch)
    assert router._resolve_config_path() == BUNDLED
    # and routing still works rather than raising on a bad path
    assert router.provider_name_for("summarize")


def test_blank_path_does_not_resolve_to_cwd(monkeypatch):
    router = _router_for("", monkeypatch)
    assert router._resolve_config_path() != router._resolve_config_path().parent
    assert router._load_config().get("providers"), "bundled config must be readable"


def test_custom_path_is_honoured(tmp_path, monkeypatch):
    custom = tmp_path / "providers.yaml"
    custom.write_text(
        yaml.safe_dump(
            {"default_provider": "mock", "task_routes": {}, "providers": {"mock": {"type": "mock"}}}
        ),
        encoding="utf-8",
    )
    router = _router_for(str(custom), monkeypatch)
    assert router._resolve_config_path() == custom
    assert set(router.providers) == {"mock"}


def test_env_example_blank_is_the_documented_local_default(monkeypatch):
    """Guard the documented contract: blank in .env must load the bundled file."""
    example = BACKEND_DIR.parent / ".env.example"
    if not example.exists():
        pytest.skip(".env.example not present")
    text = example.read_text(encoding="utf-8")
    assert "PROVIDERS_CONFIG_PATH=" in text
    lines = [ln for ln in text.splitlines() if ln.startswith("PROVIDERS_CONFIG_PATH=")]
    assert lines == ["PROVIDERS_CONFIG_PATH="], "template must keep it blank for local runs"


def test_bundled_config_declares_vision_only_for_vision_capable_vendors():
    with BUNDLED.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    providers = config["providers"]
    assert "transcribe_image" not in (providers["deepseek"].get("models") or {})
    for name in ("dashscope", "openai", "anthropic", "siliconflow"):
        assert (providers[name].get("models") or {}).get("transcribe_image"), name
