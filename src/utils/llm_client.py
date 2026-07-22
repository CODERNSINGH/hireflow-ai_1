"""
HireFlow AI — Unified LLM Client
Abstracts over multiple LLM providers behind a single interface.

All concrete clients implement:
  .chat(prompt: str) -> str
  .extract(text: str) -> dict

Usage:
    from src.utils.llm_client import get_llm_client

    client = get_llm_client()
    result = client.extract(resume_text)
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Union

from src.config.settings import get_settings

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that LLMs often add around JSON output."""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _schema_to_description(schema: Union[dict, Any]) -> str:
    """Convert a schema (dict or Pydantic model class) to a human-readable string."""
    if isinstance(schema, dict):
        return json.dumps(schema, indent=2)
    # Pydantic v2
    if hasattr(schema, "model_json_schema"):
        return json.dumps(schema.model_json_schema(), indent=2)
    # Pydantic v1
    if hasattr(schema, "schema"):
        return json.dumps(schema.schema(), indent=2)
    return str(schema)


def _build_extract_prompt(text: str, schema: Union[dict, Any]) -> str:
    """Build the extraction prompt sent to any LLM."""
    schema_desc = _schema_to_description(schema)
    return (
        "You are a structured data extraction assistant.\n"
        "Extract information from the text below and return ONLY a valid JSON object "
        "matching the following schema. Do not include any explanation, markdown fences, "
        "or extra text — just the raw JSON.\n\n"
        f"Schema:\n{schema_desc}\n\n"
        f"Text to extract from:\n{text}\n\n"
        "Return only JSON:"
    )


def _build_generic_extract_prompt(text: str) -> str:
    """Build a generic JSON-only extraction prompt."""
    return (
        "You are a structured data extraction assistant.\n"
        "Extract the useful structured information from the text below and return "
        "ONLY a valid JSON object. Do not include any explanation, markdown fences, "
        "or extra text - just the raw JSON.\n\n"
        f"Text to extract from:\n{text}\n\n"
        "Return only JSON:"
    )


def _safe_parse(raw: str) -> dict:
    """Parse LLM output to a dict, degrading gracefully on malformed JSON."""
    cleaned = _strip_markdown_fences(raw)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        logger.warning("LLM returned valid JSON but not a dict: %s", type(result))
        return {
            "error": "failed to parse LLM output",
            "raw_output": raw,
        }
    except json.JSONDecodeError as exc:
        logger.warning(
            "LLM returned malformed JSON (error: %s). Raw output: %.200s", exc, raw
        )
        return {
            "error": "failed to parse LLM output",
            "raw_output": raw,
        }


# --------------------------------------------------------------------------- #
# Abstract base
# --------------------------------------------------------------------------- #


class MissingAPIKeyError(ValueError):
    """Raised when the selected provider is missing its required API key."""


def _require_api_key(value: str | None, variable_name: str, help_url: str) -> str:
    """Return a non-empty API key or raise a clear configuration error."""
    if value and value.strip():
        return value
    raise MissingAPIKeyError(
        f"{variable_name} is not set. Add it to your .env file. "
        f"Get a key at {help_url}"
    )


class BaseLLMClient(ABC):
    """Common interface for all LLM provider clients."""

    @abstractmethod
    def chat(self, prompt: str) -> str:
        """Send a free-form prompt and return the model's text response."""

    def extract(self, text: str, schema: Union[dict, Any, None] = None) -> dict:
        """Extract structured data from *text*.

        The optional schema argument lets callers request a specific output shape
        while the simple extract(text) form remains available everywhere.
        """
        prompt = (
            _build_extract_prompt(text, schema)
            if schema is not None
            else _build_generic_extract_prompt(text)
        )
        try:
            raw = self.chat(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM chat call failed during extraction: %s", exc)
            return {
                "error": "failed to parse LLM output",
                "raw_output": str(exc),
            }
        return _safe_parse(raw)


# --------------------------------------------------------------------------- #
# Concrete clients
# --------------------------------------------------------------------------- #


class GroqClient(BaseLLMClient):
    """Client for the Groq inference API (free tier, fast Llama/Mixtral)."""

    def __init__(self, settings: Any | None = None) -> None:
        settings = settings or get_settings()
        api_key = _require_api_key(
            settings.GROQ_API_KEY,
            "GROQ_API_KEY",
            "https://console.groq.com",
        )

        try:
            from groq import Groq  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'groq' package is not installed. Run: pip install groq"
            ) from exc

        self._client = Groq(api_key=api_key)
        self._model = getattr(settings, "GROQ_MODEL", "llama-3.1-8b-instant")

    def chat(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


class GeminiClient(BaseLLMClient):
    """Client for Google Gemini (free tier via google-generativeai)."""

    def __init__(self, settings: Any | None = None) -> None:
        settings = settings or get_settings()
        api_key = _require_api_key(
            getattr(settings, "GEMINI_API_KEY", None)
            or getattr(settings, "GOOGLE_API_KEY", None),
            "GEMINI_API_KEY or GOOGLE_API_KEY",
            "https://aistudio.google.com",
        )

        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'google-generativeai' package is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
        )

    def chat(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        return response.text or ""


class OpenAIClient(BaseLLMClient):
    """Client for the OpenAI API (GPT-4o, GPT-4-turbo, etc.)."""

    def __init__(self, settings: Any | None = None) -> None:
        settings = settings or get_settings()
        api_key = _require_api_key(
            settings.OPENAI_API_KEY,
            "OPENAI_API_KEY",
            "https://platform.openai.com/api-keys",
        )

        try:
            from openai import OpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc

        self._client = OpenAI(api_key=api_key)
        self._model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")

    def chat(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic's Claude models."""

    def __init__(self, settings: Any | None = None) -> None:
        settings = settings or get_settings()
        api_key = _require_api_key(
            settings.ANTHROPIC_API_KEY,
            "ANTHROPIC_API_KEY",
            "https://console.anthropic.com/settings/keys",
        )

        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = getattr(settings, "ANTHROPIC_MODEL", "claude-3-haiku-20240307")

    def chat(self, prompt: str) -> str:
        message = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        # content is a list of ContentBlock objects
        return message.content[0].text if message.content else ""


class OllamaClient(BaseLLMClient):
    """Client for locally-running Ollama models (no API key required)."""

    def __init__(self, settings: Any | None = None) -> None:
        try:
            import requests  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'requests' package is not installed. Run: pip install requests"
            ) from exc

        settings = settings or get_settings()
        self._base_url = getattr(
            settings, "OLLAMA_BASE_URL", "http://localhost:11434"
        ).rstrip("/")
        self._model = getattr(settings, "OLLAMA_MODEL", "llama3")
        self._requests = requests

    def chat(self, prompt: str) -> str:
        url = f"{self._base_url}/api/generate"
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        response = self._requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("response", "")


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def get_llm_client(settings: Any | None = None) -> BaseLLMClient:
    """Instantiate and return the correct LLM client based on settings.LLM_PROVIDER.

    Raises MissingAPIKeyError with a descriptive human-readable message if the
    required API key for the selected provider is missing.
    """
    settings = settings or get_settings()
    provider = settings.LLM_PROVIDER.lower().strip()

    clients: dict[str, type[BaseLLMClient]] = {
        "groq": GroqClient,
        "gemini": GeminiClient,
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "ollama": OllamaClient,
    }

    if provider in clients:
        return clients[provider](settings)

    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'. Must be one of: "
        "groq, gemini, openai, anthropic, ollama"
    )
