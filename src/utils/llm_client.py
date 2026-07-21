"""
HireFlow AI — Unified LLM Client
Abstracts over multiple LLM providers behind a single interface.

All concrete clients implement:
  .chat(prompt: str) -> str
  .extract(text: str, schema: dict | type[BaseModel]) -> dict

Usage:
    from src.utils.llm_client import get_llm_client
    from src.config.settings import get_settings

    client = get_llm_client(get_settings())
    result = client.extract(resume_text, ProfileExtractSchema)
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Union

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


def _safe_parse(raw: str) -> dict:
    """Parse LLM output to a dict, degrading gracefully on malformed JSON."""
    cleaned = _strip_markdown_fences(raw)
    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
        logger.warning("LLM returned valid JSON but not a dict: %s", type(result))
        return {}
    except json.JSONDecodeError as exc:
        logger.warning(
            "LLM returned malformed JSON (error: %s). Raw output: %.200s", exc, raw
        )
        return {}


# --------------------------------------------------------------------------- #
# Abstract base
# --------------------------------------------------------------------------- #


class BaseLLMClient(ABC):
    """Common interface for all LLM provider clients."""

    @abstractmethod
    def chat(self, prompt: str) -> str:
        """Send a free-form prompt and return the model's text response."""

    def extract(self, text: str, schema: Union[dict, Any]) -> dict:
        """Extract structured data from *text* matching *schema*.

        Returns a dict. Never raises — on LLM or parse errors it returns
        an empty dict and logs a warning so callers always get a usable result.
        """
        prompt = _build_extract_prompt(text, schema)
        try:
            raw = self.chat(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM chat call failed during extraction: %s", exc)
            return {}
        return _safe_parse(raw)


# --------------------------------------------------------------------------- #
# Concrete clients
# --------------------------------------------------------------------------- #


class GroqClient(BaseLLMClient):
    """Client for the Groq inference API (free tier, fast Llama/Mixtral)."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from groq import Groq  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'groq' package is not installed. Run: pip install groq"
            ) from exc

        self._client = Groq(api_key=api_key)
        self._model = model

    def chat(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


class GeminiClient(BaseLLMClient):
    """Client for Google Gemini (free tier via google-generativeai)."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'google-generativeai' package is not installed. "
                "Run: pip install google-generativeai"
            ) from exc

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    def chat(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        return response.text or ""


class OpenAIClient(BaseLLMClient):
    """Client for the OpenAI API (GPT-4o, GPT-4-turbo, etc.)."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        try:
            from openai import OpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def chat(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic's Claude models."""

    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307") -> None:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

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

    def __init__(self, base_url: str, model: str) -> None:
        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'httpx' package is not installed. Run: pip install httpx"
            ) from exc

        self._base_url = base_url.rstrip("/")
        self._model = model
        self._httpx = httpx

    def chat(self, prompt: str) -> str:
        url = f"{self._base_url}/api/generate"
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        response = self._httpx.post(url, json=payload, timeout=120)
        response.raise_for_status()
        return response.json().get("response", "")


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def get_llm_client(settings: Any) -> BaseLLMClient:
    """Instantiate and return the correct LLM client based on settings.LLM_PROVIDER.

    Raises ValueError with a descriptive human-readable message if the required
    API key for the selected provider is missing — never a bare AttributeError or
    stack trace.
    """
    provider = settings.LLM_PROVIDER.lower().strip()

    if provider == "groq":
        if not settings.GROQ_API_KEY:
            raise ValueError(
                "LLM_PROVIDER is set to 'groq' but GROQ_API_KEY is not set. "
                "Get a free key at console.groq.com and add it to your .env file."
            )
        return GroqClient(api_key=settings.GROQ_API_KEY, model=settings.GROQ_MODEL)

    if provider == "gemini":
        if not settings.GOOGLE_API_KEY:
            raise ValueError(
                "LLM_PROVIDER is set to 'gemini' but GOOGLE_API_KEY is not set. "
                "Get a free key at aistudio.google.com and add it to your .env file."
            )
        return GeminiClient(
            api_key=settings.GOOGLE_API_KEY, model=settings.GEMINI_MODEL
        )

    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "LLM_PROVIDER is set to 'openai' but OPENAI_API_KEY is not set. "
                "Add your OpenAI key to the .env file."
            )
        return OpenAIClient(api_key=settings.OPENAI_API_KEY)

    if provider == "anthropic":
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError(
                "LLM_PROVIDER is set to 'anthropic' but ANTHROPIC_API_KEY is not set. "
                "Add your Anthropic key to the .env file."
            )
        return AnthropicClient(api_key=settings.ANTHROPIC_API_KEY)

    if provider == "ollama":
        return OllamaClient(
            base_url=settings.OLLAMA_BASE_URL, model=settings.OLLAMA_MODEL
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER: '{settings.LLM_PROVIDER}'. "
        "Valid options are: groq, gemini, openai, anthropic, ollama. "
        "Check your .env file."
    )
