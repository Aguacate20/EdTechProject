"""
pipeline/llm_client.py — v2.2.2

Cliente que enruta cada llamada a través del pool de modelos.

Cambios respecto a v2.1:

  1. RUTEO POR CAPACIDAD. Ya no hay un proveedor global. Cada llamada declara
     el tier de calidad que necesita y su techo de tokens; el pool elige el
     modelo que puede atenderla antes. Como los límites son por modelo, esto
     multiplica el rendimiento sin pagar nada.

  2. LIMITADOR PROPIO. Se reserva cupo ANTES de pedir, con la misma cuenta que
     hace el proveedor (entrada estimada + techo de salida). En la corrida
     medida, 35 de ~99 peticiones fueron rechazadas con 429 y cada una costaba
     un minuto: más de la mitad del tiempo total se fue en castigos evitables.

  3. SINCRONIZACIÓN CON LAS CABECERAS. Los proveedores informan el cupo
     restante real en cada respuesta. Nuestra estimación de entrada es
     aproximada; sincronizar corrige la deriva.

  4. FALLBACK ENTRE MODELOS. Si el elegido falla con error reintentable, se
     intenta con el siguiente del pool en vez de insistir contra el mismo.

Se conserva de v2.1 lo que funcionó: reintentos solo sobre errores
reintentables, detección de truncamiento por `finish_reason`, y el rescate de
los elementos completos de un JSON cortado.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

import httpx

from .model_pool import NoCapacity, get_pool
from .ratelimit import estimate_input_tokens

logger = logging.getLogger(__name__)

PROVIDER_ENDPOINTS = {
    "cerebras": ("https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "GOOGLE_API_KEY"),
    "hf": ("https://router.huggingface.co/v1/chat/completions", "HF_TOKEN"),
    "claude": ("https://api.anthropic.com/v1/messages", "ANTHROPIC_API_KEY"),
}

HTTP_TIMEOUT = float(os.environ.get("LLM_HTTP_TIMEOUT", "120"))

# Nombre del parámetro de techo de tokens por modelo.
#
# v2.2 mandaba `max_tokens` y `max_completion_tokens` a la vez, como red de
# seguridad por si algún proveedor ignoraba el nombre nuevo. Cerebras rechaza
# esa combinación con 400 explícito: "Setting max_tokens and
# max_completion_tokens at the same time is not supported".
#
# Ahora se manda UNO solo, y si el proveedor se queja del nombre se cambia al
# otro y se reintenta. El aprendizaje queda cacheado por modelo, así que el
# costo es una sola llamada fallida por modelo y por arranque.
_DEFAULT_TOKEN_PARAM = os.environ.get("LLM_TOKEN_PARAM", "max_completion_tokens")
_TOKEN_PARAM: dict[str, str] = {}


def _token_param(entry: dict) -> str:
    return _TOKEN_PARAM.get(entry["key"]) or entry.get("token_param") or _DEFAULT_TOKEN_PARAM


def _flip_token_param(entry: dict) -> str:
    actual = _token_param(entry)
    nuevo = "max_tokens" if actual == "max_completion_tokens" else "max_completion_tokens"
    _TOKEN_PARAM[entry["key"]] = nuevo
    logger.warning("[llm] %s no acepta '%s'; se cambia a '%s'", entry["key"], actual, nuevo)
    return nuevo
MAX_MODEL_ATTEMPTS = int(os.environ.get("LLM_MAX_MODEL_ATTEMPTS", "3"))


class LLMError(Exception):
    """Base."""


class LLMRetryable(LLMError):
    """Red, timeout, 429 o 5xx."""


class LLMTruncated(LLMError):
    def __init__(self, message: str, partial: dict | None = None):
        super().__init__(message)
        self.partial = partial


class LLMParseError(LLMError):
    """La respuesta no es JSON recuperable."""


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.1,
    tier: str = "alta",
    label: str = "",
    provider: str | None = None,
    allow_salvage: bool = True,
) -> dict[str, Any]:
    """Enruta, espera cupo, llama y devuelve el JSON parseado."""
    pool = get_pool()
    estimated = estimate_input_tokens(system_prompt, user_prompt) + max_tokens

    last_error: Exception | None = None
    tried: list[str] = []

    for _ in range(MAX_MODEL_ATTEMPTS):
        try:
            entry, waited = await pool.acquire(tier, estimated)
        except NoCapacity as e:
            raise LLMError(str(e)) from e

        if entry["key"] in tried:
            # Ya falló; dar tiempo a que el pool cambie de estado.
            await asyncio.sleep(2)
        tried.append(entry["key"])

        started = time.monotonic()
        try:
            text, finish, usage, headers = await _request(
                entry, system_prompt, user_prompt, min(max_tokens, entry.get("max_output", 8000)),
                temperature,
            )
        except LLMRetryable as e:
            last_error = e
            logger.warning("[llm] %s falló en %s (%s); probando otro modelo",
                           label or "-", entry["key"], str(e)[:120])
            continue

        pool.sync(entry["key"], headers)
        elapsed = time.monotonic() - started
        logger.info(
            "[llm] %s | %s | %.1fs (espera %.1fs) | in=%s out=%s est=%d | finish=%s",
            label or "-", entry["key"], elapsed, waited,
            usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"),
            estimated, finish,
        )

        if finish == "length":
            partial = _salvage_truncated(text) if allow_salvage else None
            if partial is not None:
                logger.warning("[llm] %s: truncado, rescatados %d elementos",
                               label or "-", _count_items(partial))
                raise LLMTruncated(f"Respuesta truncada en {label}", partial=partial)
            raise LLMTruncated(f"Respuesta truncada y no rescatable en {label}")

        parsed = _parse_json_response(text, allow_salvage=allow_salvage)
        if parsed is None:
            raise LLMParseError(
                f"JSON no parseable en {label} ({entry['key']}). Inicio: {text[:250]}"
            )
        return parsed

    raise LLMError(
        f"Sin éxito en {label} tras probar {tried}. Último error: {last_error}"
    )


async def _request(
    entry: dict, system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float,
) -> tuple[str, str, dict, dict]:
    provider = entry["provider"]
    url, token_env = PROVIDER_ENDPOINTS[provider]
    token = os.environ.get(token_env)
    if not token:
        raise LLMError(f"Falta {token_env} para {entry['key']}")

    if provider == "claude":
        return await _call_claude(entry, url, token, system_prompt, user_prompt,
                                  max_tokens, temperature)
    return await _call_openai_compatible(entry, url, token, system_prompt, user_prompt,
                                         max_tokens, temperature)


async def _call_openai_compatible(
    entry: dict, url: str, token: str,
    system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float,
) -> tuple[str, str, dict, dict]:
    model = entry["model"]
    if "gemma" in model.lower():
        messages = [{"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}]
    else:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    # Un solo nombre. El proveedor estima el consumo con este número, así que
    # si no lo reconoce cuenta la longitud máxima de secuencia y nos limita sin
    # motivo; por eso importa acertar y por eso hay auto-corrección abajo.
    payload = {
        "model": model,
        "messages": messages,
        _token_param(entry): max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        _handle_status_error(entry, e)
        raise
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise LLMRetryable(f"Red hacia {entry['key']}: {e}") from e

    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    return (text, choice.get("finish_reason") or "stop",
            data.get("usage") or {}, dict(response.headers))


async def _call_claude(
    entry: dict, url: str, token: str,
    system_prompt: str, user_prompt: str,
    max_tokens: int, temperature: float,
) -> tuple[str, str, dict, dict]:
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": entry["model"], "max_tokens": max_tokens, "temperature": temperature,
        "system": system_prompt, "messages": [{"role": "user", "content": user_prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        _handle_status_error(entry, e)
        raise
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise LLMRetryable(f"Red hacia {entry['key']}: {e}") from e

    text = (data.get("content") or [{}])[0].get("text", "")
    finish = "length" if data.get("stop_reason") == "max_tokens" else "stop"
    usage = data.get("usage") or {}
    return (text, finish,
            {"prompt_tokens": usage.get("input_tokens"),
             "completion_tokens": usage.get("output_tokens")},
            dict(response.headers))


# "Current length is 9689 while limit is 8192" y variantes de otros proveedores.
_CONTEXT_LIMIT_PATTERNS = [
    re.compile(r"limit is\s+(\d{3,7})", re.I),
    re.compile(r"maximum context length is\s+(\d{3,7})", re.I),
    re.compile(r"context[_ ]length[^0-9]{0,40}?(\d{3,7})", re.I),
]


def _parse_context_limit(body: str) -> int | None:
    for pattern in _CONTEXT_LIMIT_PATTERNS:
        match = pattern.search(body)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _handle_status_error(entry: dict, e: httpx.HTTPStatusError) -> None:
    status = e.response.status_code
    pool = get_pool()
    if status == 400:
        body = e.response.text or ""
        # Rechazo por ventana de contexto. El proveedor informa su límite real
        # en el mensaje, así que se aprende y se prueba con otro modelo en vez
        # de dar la capa por perdida.
        if "context_length_exceeded" in body or "reduce the length" in body.lower():
            limite = _parse_context_limit(body)
            if limite:
                pool.learn_context_limit(entry["key"], limite)
            raise LLMRetryable(
                f"Ventana de contexto excedida en {entry['key']}"
                + (f" (límite real {limite})" if limite else "")
            ) from e
        if "max_completion_tokens" in body or "max_tokens" in body:
            _flip_token_param(entry)
            raise LLMRetryable(
                f"400 por nombre del parámetro de tokens en {entry['key']}; reintentando"
            ) from e
    if status == 429:
        wait_s = _retry_after(e.response) or 60.0
        # Si llegamos acá, nuestra estimación se quedó corta: se castiga la
        # cubeta de ese modelo y se prueba otro en vez de dormir un minuto.
        pool.penalize(entry["key"], wait_s)
        pool.sync(entry["key"], dict(e.response.headers))
        raise LLMRetryable(f"429 en {entry['key']} (pide {wait_s:.0f}s)") from e
    if status >= 500:
        pool.penalize(entry["key"], 10)
        raise LLMRetryable(f"{status} en {entry['key']}") from e
    raise LLMError(f"{status} en {entry['key']}: {e.response.text[:250]}") from e


def _retry_after(response: httpx.Response) -> float | None:
    for header in ("retry-after", "x-ratelimit-reset-tokens-minute",
                   "x-ratelimit-reset-requests-minute", "x-ratelimit-reset-tokens"):
        value = response.headers.get(header)
        if not value:
            continue
        try:
            parsed = float(re.sub(r"[^0-9.]", "", value) or 0)
            if parsed > 0:
                return parsed
        except ValueError:
            continue
    return None


# ─────────────────────────────────────────────
# Parseo (sin cambios funcionales respecto a v2.1)
# ─────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    return re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()


def _parse_json_response(text: str, allow_salvage: bool = True) -> dict[str, Any] | None:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            pass
    return _salvage_truncated(text) if allow_salvage else None


def _salvage_truncated(text: str) -> dict[str, Any] | None:
    """Rescata los elementos completos de un JSON cortado a mitad."""
    text = _strip_fences(text)
    start = text.find("{")
    if start < 0:
        return None
    s = text[start:]

    stack: list[str] = []
    in_string = False
    escaped = False
    last_good: int | None = None
    last_good_stack: list[str] = []

    for i, ch in enumerate(s):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            if stack and stack[-1] == "[":
                last_good = i + 1
                last_good_stack = list(stack)

    if not stack or last_good is None:
        return None
    closers = "".join("}" if c == "{" else "]" for c in reversed(last_good_stack))
    try:
        return json.loads(s[:last_good] + closers)
    except json.JSONDecodeError:
        return None


def _count_items(parsed: dict) -> int:
    return sum(len(v) for v in parsed.values() if isinstance(v, list))
