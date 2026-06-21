from types import SimpleNamespace

import pytest

from app.llm import AnthropicProvider, EMOTIONS, OpenAIProvider, fallback_analysis
from app.auth import hash_password, verify_password
from app.matching import emotion_complementarity, emotion_similarity


def emotion(**overrides):
    base = {
        "distribution": {name: 1.0 if name == "焦虑" else 0.0 for name in EMOTIONS},
        "valence": -0.5,
        "arousal": 0.8,
        "intensity": 0.7,
        "keywords": ["压力", "担心"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_similar_emotions_match():
    assert emotion_similarity(emotion(), emotion()) == 1.0


def test_opposite_emotions_do_not_match():
    other = emotion(
        distribution={name: 1.0 if name == "喜悦" else 0.0 for name in EMOTIONS},
        valence=0.9,
        arousal=0.2,
        intensity=0.2,
        keywords=["庆祝"],
    )
    assert emotion_similarity(emotion(), other) < 0.65


def test_complementary_matching_rewards_shared_context_and_balanced_energy():
    calmer_peer = emotion(arousal=0.45, intensity=0.6, keywords=["压力", "倾听"])
    unrelated_peer = emotion(
        distribution={name: 1.0 if name == "喜悦" else 0.0 for name in EMOTIONS},
        valence=0.9, arousal=0.1, intensity=0.2, keywords=["庆祝"],
    )
    assert emotion_complementarity(emotion(), calmer_peer) > emotion_complementarity(emotion(), unrelated_peer)


def test_password_hash_is_argon2_and_verifies():
    password_hash = hash_password("a-safe-password")
    assert password_hash.startswith("$argon2")
    assert verify_password(password_hash, "a-safe-password") is True
    assert verify_password(password_hash, "wrong-password") is False


def test_fallback_detects_crisis_and_is_degraded():
    result = fallback_analysis("我太痛苦了，甚至不想活了")
    assert result.safety_level == "crisis"
    assert result.degraded is True
    assert set(result.distribution) == set(EMOTIONS)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.response)


@pytest.mark.asyncio
async def test_openai_standard_adapter(monkeypatch):
    calls = []
    settings = SimpleNamespace(
        openai_base_url="https://provider.example/v1/",
        openai_api_key="secret",
        openai_model="deepseekpro",
        llm_timeout_seconds=5,
    )
    monkeypatch.setattr(
        "app.llm.httpx.AsyncClient",
        lambda **_: FakeClient({"choices": [{"message": {"content": "ok"}}]}, calls),
    )
    assert await OpenAIProvider(settings).complete("system", "hello", 100) == "ok"
    url, request = calls[0]
    assert url == "https://provider.example/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["json"]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_openai_adapter_rejects_empty_reasoning_only_response(monkeypatch):
    settings = SimpleNamespace(
        openai_base_url="https://provider.example/v1/",
        openai_api_key="secret",
        openai_model="reasoning-model",
        llm_timeout_seconds=5,
    )
    monkeypatch.setattr(
        "app.llm.httpx.AsyncClient",
        lambda **_: FakeClient({
            "choices": [{
                "finish_reason": "length",
                "message": {"content": "", "reasoning_content": "thinking"},
            }]
        }, []),
    )
    with pytest.raises(RuntimeError, match="未返回正文"):
        await OpenAIProvider(settings).complete("system", "hello", 100)


@pytest.mark.asyncio
async def test_anthropic_standard_adapter(monkeypatch):
    calls = []
    settings = SimpleNamespace(
        anthropic_base_url="https://provider.example/v1/",
        anthropic_api_key="secret",
        anthropic_model="deepseekpro",
        llm_timeout_seconds=5,
    )
    monkeypatch.setattr(
        "app.llm.httpx.AsyncClient",
        lambda **_: FakeClient({"content": [{"type": "text", "text": "ok"}]}, calls),
    )
    assert await AnthropicProvider(settings).complete("system", "hello", 100) == "ok"
    url, request = calls[0]
    assert url == "https://provider.example/v1/messages"
    assert request["headers"]["x-api-key"] == "secret"
    assert request["headers"]["anthropic-version"] == "2023-06-01"
    assert request["json"]["system"] == "system"
