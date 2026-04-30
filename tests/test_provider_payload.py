"""Unit tests for GROK_WEB_SEARCH_TOOL flag effect on payload construction.

Run: python -m pytest tests/test_provider_payload.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from grok_search.config import config
from grok_search.providers.grok import GrokSearchProvider


class _DummyResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": []}


class _PayloadCapture:
    """Captures the JSON payload sent to httpx.AsyncClient.post."""

    def __init__(self):
        self.payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        self.payload = json
        return _DummyResponse(json or {})


@pytest.fixture
def capture(monkeypatch):
    cap = _PayloadCapture()

    def _client_factory(*args, **kwargs):
        return cap

    monkeypatch.setattr(
        "grok_search.providers.grok.httpx.AsyncClient",
        _client_factory,
    )
    return cap


@pytest.mark.asyncio
@pytest.mark.parametrize("env_value", ["true", "1", "yes", "TRUE", "True", "Yes", "YES"])
async def test_truthy_values_inject_tools(monkeypatch, capture, env_value):
    monkeypatch.setenv("GROK_WEB_SEARCH_TOOL", env_value)
    assert config.web_search_tool_enabled is True
    provider = GrokSearchProvider("https://example.invalid", "k", "grok-4-fast")
    await provider.search("hello")
    assert capture.payload is not None
    assert capture.payload.get("tools") == [{"type": "web_search"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("env_value", ["false", "0", "no", "FALSE", "False", "NO", "off", "unknown", ""])
async def test_falsy_or_unknown_values_omit_tools(monkeypatch, capture, env_value):
    monkeypatch.setenv("GROK_WEB_SEARCH_TOOL", env_value)
    assert config.web_search_tool_enabled is False
    provider = GrokSearchProvider("https://example.invalid", "k", "grok-4-fast")
    await provider.search("hello")
    assert capture.payload is not None
    assert "tools" not in capture.payload


@pytest.mark.asyncio
async def test_default_unset_injects_tools(monkeypatch, capture):
    monkeypatch.delenv("GROK_WEB_SEARCH_TOOL", raising=False)
    assert config.web_search_tool_enabled is True
    provider = GrokSearchProvider("https://example.invalid", "k", "grok-4-fast")
    await provider.search("hello")
    assert capture.payload is not None
    assert capture.payload.get("tools") == [{"type": "web_search"}]


@pytest.mark.asyncio
async def test_payload_other_fields_unchanged(monkeypatch, capture):
    """Disabling the flag must not affect model/input fields."""
    monkeypatch.setenv("GROK_WEB_SEARCH_TOOL", "false")
    provider = GrokSearchProvider("https://example.invalid", "k", "grok-4-fast")
    await provider.search("hello", platform="GitHub")
    p = capture.payload
    assert p["model"] == "grok-4-fast"
    assert isinstance(p["input"], list) and len(p["input"]) == 2
    assert p["input"][0]["role"] == "system"
    assert p["input"][1]["role"] == "user"
    assert "GitHub" in p["input"][1]["content"]


def test_get_config_info_exposes_flag(monkeypatch):
    monkeypatch.setenv("GROK_WEB_SEARCH_TOOL", "false")
    monkeypatch.setenv("GROK_API_URL", "https://example.invalid/v1")
    monkeypatch.setenv("GROK_API_KEY", "test-key")
    info = config.get_config_info()
    assert "GROK_WEB_SEARCH_TOOL" in info
    assert info["GROK_WEB_SEARCH_TOOL"] is False

    monkeypatch.setenv("GROK_WEB_SEARCH_TOOL", "true")
    info2 = config.get_config_info()
    assert info2["GROK_WEB_SEARCH_TOOL"] is True


def test_get_config_info_flag_present_when_api_unset(monkeypatch):
    """Flag must be exposed even when GROK_API_URL/KEY missing (i.e. outside try)."""
    monkeypatch.delenv("GROK_API_URL", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.setenv("GROK_WEB_SEARCH_TOOL", "false")
    info = config.get_config_info()
    assert "GROK_WEB_SEARCH_TOOL" in info
    assert info["GROK_WEB_SEARCH_TOOL"] is False
