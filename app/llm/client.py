"""Unified LLM client supporting OpenAI and Google Gemini."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import LLMProvider, get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Concurrency limiter ──────────────────────────────────────────────
# Prevents overloading the LLM API when many jobs run in parallel.
_llm_semaphore = asyncio.Semaphore(settings.llm_concurrency)


@dataclass
class LLMResponse:
    """Normalised response from any LLM provider."""
    raw_text: str
    parsed_json: Optional[dict] = None
    tokens_used: int = 0
    latency_ms: float = 0.0
    error: Optional[str] = None


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that LLMs sometimes add."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def call_llm(prompt: str, model_override: Optional[str] = None) -> LLMResponse:
    """Send *prompt* to the configured LLM and return a normalised response.

    Acquires a semaphore slot (default 50) to cap concurrent API calls.
    
    Args:
        prompt: The prompt to send to the LLM
        model_override: Optional model name to use instead of the default.
                       Use for fallback routing (cheaper model for retries).
    """
    async with _llm_semaphore:
        provider = settings.llm_provider
        try:
            if provider == LLMProvider.OPENAI:
                return await _call_openai(prompt, model_override)
            elif provider == LLMProvider.GEMINI:
                return await _call_gemini(prompt, model_override)
            else:
                return LLMResponse(raw_text="", error=f"Unknown provider: {provider}")
        except Exception as exc:
            logger.exception("LLM call failed")
            return LLMResponse(raw_text="", error=str(exc))


# ═══════════════════════════════════════════════════════════════════════
# OpenAI
# ═══════════════════════════════════════════════════════════════════════

async def _call_openai(prompt: str, model_override: Optional[str] = None) -> LLMResponse:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = model_override or settings.openai_model

    start = time.perf_counter()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a JSON-only data extraction assistant. "
                           "Always respond with valid JSON and nothing else.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    content = response.choices[0].message.content or ""
    tokens = response.usage.total_tokens if response.usage else 0

    cleaned = _strip_markdown_fences(content)
    parsed = None
    error = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        error = f"JSON parse error: {e}"
        logger.warning("OpenAI response is not valid JSON: %s", e)

    return LLMResponse(
        raw_text=content,
        parsed_json=parsed,
        tokens_used=tokens,
        latency_ms=round(elapsed_ms, 2),
        error=error,
    )


# ═══════════════════════════════════════════════════════════════════════
# Google Gemini
# ═══════════════════════════════════════════════════════════════════════

async def _call_gemini(prompt: str, model_override: Optional[str] = None) -> LLMResponse:
    import google.generativeai as genai

    genai.configure(api_key=settings.gemini_api_key)
    model_name = model_override or settings.gemini_model
    model = genai.GenerativeModel(model_name)

    start = time.perf_counter()
    response = await model.generate_content_async(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_tokens,
        ),
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    content = response.text or ""
    # Gemini doesn't always expose token counts via the same API surface
    tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        tokens = getattr(response.usage_metadata, "total_token_count", 0)

    cleaned = _strip_markdown_fences(content)
    parsed = None
    error = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        error = f"JSON parse error: {e}"
        logger.warning("Gemini response is not valid JSON: %s", e)

    return LLMResponse(
        raw_text=content,
        parsed_json=parsed,
        tokens_used=tokens,
        latency_ms=round(elapsed_ms, 2),
        error=error,
    )
