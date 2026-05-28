"""
pipeline/llm_client.py

Cliente LLM con soporte para múltiples proveedores.
Proveedor activo se controla con la variable LLM_PROVIDER en .env

Proveedores soportados:
  groq   → Groq Cloud (FREE, recomendado para desarrollo)
           Modelo: llama-3.3-70b-versatile
           Límites gratis: 14.400 req/día · 6.000 tokens/min

  hf     → Hugging Face Inference API (FREE, más lento)
           Modelo: meta-llama/Llama-3.3-70B-Instruct

  claude → Anthropic Claude Sonnet (de pago, producción)
           Modelo: claude-sonnet-4-20250514
"""
import json
import os
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# ── Configuración por proveedor ────────────────────────────────────────────────

PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "gemma2-9b-it",
        "token_env": "GROQ_API_KEY",
        "max_tokens_limit": 8000,
    },
    "hf": {
        "url": "https://api-inference.huggingface.co/models/meta-llama/Llama-3.3-70B-Instruct/v1/chat/completions",
        "model": "meta-llama/Llama-3.3-70B-Instruct",
        "token_env": "HF_TOKEN",
        "max_tokens_limit": 4096,
    },
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-20250514",
        "token_env": "ANTHROPIC_API_KEY",
        "max_tokens_limit": 8096,
    },
}

def _get_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "groq").lower()


# ── Cliente principal ─────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=2, min=5, max=30))
async def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """
    Llama al LLM activo y retorna el JSON parseado.
    El proveedor se elige por LLM_PROVIDER en .env (default: groq).
    """
    provider_name = _get_provider()
    provider = PROVIDERS.get(provider_name)
    if not provider:
        raise ValueError(f"Proveedor desconocido: {provider_name}. Opciones: {list(PROVIDERS)}")

    token = os.environ.get(provider["token_env"])
    if not token:
        raise EnvironmentError(
            f"Variable {provider['token_env']} no configurada para proveedor '{provider_name}'"
        )

    # Limitar max_tokens al máximo del proveedor
    max_tokens = min(max_tokens, provider["max_tokens_limit"])

    if provider_name == "claude":
        raw_text = await _call_claude(provider, token, system_prompt, user_prompt, max_tokens, temperature)
    else:
        raw_text = await _call_openai_compatible(provider, token, system_prompt, user_prompt, max_tokens, temperature)

    return _parse_json_response(raw_text)


async def _call_openai_compatible(
    provider: dict, token: str,
    system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float,
) -> str:
    """Groq y HF usan la misma interfaz OpenAI-compatible."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(provider["url"], headers=headers, json=payload)
        response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def _call_claude(
    provider: dict, token: str,
    system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float,
) -> str:
    """Cliente específico para Anthropic API."""
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": provider["model"],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(provider["url"], headers=headers, json=payload)
        response.raise_for_status()
    data = response.json()
    return data["content"][0]["text"]


# ── Parser de respuesta ───────────────────────────────────────────────────────

def _parse_json_response(text: str) -> dict[str, Any]:
    """Extrae JSON del texto del LLM, tolerando markdown code blocks."""
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = text.rstrip("`").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(f"No se pudo parsear JSON del LLM.\nTexto:\n{text[:500]}")
