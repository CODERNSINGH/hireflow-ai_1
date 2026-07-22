from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from src.utils.llm_client import BaseLLMClient, MissingAPIKeyError, get_llm_client


def _settings(provider: str, **overrides):
    base = {
        "LLM_PROVIDER": provider,
        "GROQ_API_KEY": None,
        "GROQ_MODEL": "llama-3.1-8b-instant",
        "GEMINI_API_KEY": None,
        "GOOGLE_API_KEY": None,
        "GEMINI_MODEL": "gemini-1.5-flash",
        "OPENAI_API_KEY": None,
        "ANTHROPIC_API_KEY": None,
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "llama3",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class StubLLMClient(BaseLLMClient):
    def __init__(self, response: str) -> None:
        self.response = response

    def chat(self, prompt: str) -> str:
        return self.response


@pytest.mark.parametrize(
    ("provider", "env_var", "message"),
    [
        ("groq", "GROQ_API_KEY", "GROQ_API_KEY is not set"),
        ("gemini", "GEMINI_API_KEY", "GEMINI_API_KEY or GOOGLE_API_KEY is not set"),
        ("openai", "OPENAI_API_KEY", "OPENAI_API_KEY is not set"),
        ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY is not set"),
    ],
)
def test_get_llm_client_missing_api_key_is_helpful(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    env_var: str,
    message: str,
) -> None:
    monkeypatch.delenv(env_var, raising=False)

    with pytest.raises(MissingAPIKeyError, match=message):
        get_llm_client(_settings(provider))


def test_get_llm_client_invalid_provider_raises_value_error() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "Unknown LLM_PROVIDER 'not-a-provider'. Must be one of: "
            "groq, gemini, openai, anthropic, ollama"
        ),
    ):
        get_llm_client(_settings("not-a-provider"))


def test_extract_strips_markdown_json_fences() -> None:
    client = StubLLMClient('```json\n{"skills": ["Python", "FastAPI"]}\n```')

    assert client.extract("resume text") == {"skills": ["Python", "FastAPI"]}


def test_extract_returns_fallback_dict_for_malformed_json() -> None:
    raw_output = "Here are the skills: Python, FastAPI"
    client = StubLLMClient(raw_output)

    assert client.extract("resume text") == {
        "error": "failed to parse LLM output",
        "raw_output": raw_output,
    }


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_groq_extract_integration_returns_non_empty_dict() -> None:
    client = get_llm_client(_settings("groq", GROQ_API_KEY=os.environ["GROQ_API_KEY"]))

    result = client.extract(
        "Extract skills as a list from: Python developer with FastAPI and "
        "Docker experience"
    )

    assert isinstance(result, dict)
    assert result
    assert "error" not in result
