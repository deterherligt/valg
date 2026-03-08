import pytest
from unittest.mock import patch, MagicMock
from valg.ai import build_prompt, get_ai_client, is_ai_configured


def test_is_ai_configured_false_without_env(monkeypatch):
    monkeypatch.delenv("VALG_AI_API_KEY", raising=False)
    assert is_ai_configured() is False


def test_is_ai_configured_true_with_key(monkeypatch):
    monkeypatch.setenv("VALG_AI_API_KEY", "sk-test")
    monkeypatch.setenv("VALG_AI_BASE_URL", "https://api.anthropic.com/v1")
    monkeypatch.setenv("VALG_AI_MODEL", "claude-sonnet-4-6")
    assert is_ai_configured() is True


def test_build_prompt_contains_party_data():
    state = {
        "parties": [{"letter": "A", "votes": 50000, "seats": 3}],
        "districts_reported": 10,
        "districts_total": 20,
    }
    prompt = build_prompt(state)
    assert "A" in prompt
    assert "50000" in prompt or "50,000" in prompt


def test_build_prompt_returns_string():
    state = {"parties": [], "districts_reported": 0, "districts_total": 0}
    assert isinstance(build_prompt(state), str)


def test_get_commentary_returns_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("VALG_AI_API_KEY", raising=False)
    from valg.ai import get_commentary
    result = get_commentary({"parties": [], "districts_reported": 0, "districts_total": 0})
    assert result is None
