"""
pipeline/model_pool.py — NUEVO en v2.2

Catálogo de modelos y enrutador por capacidad.

El hallazgo que hace falta esta pieza: los límites de tasa se aplican POR
MODELO, no por cuenta. Tres modelos en Cerebras son tres cubetas
independientes de 5 RPM y 30K TPM; sumar Groq agrega otras tres. Repartir la
carga multiplica el rendimiento sin pagar nada.

Y hay una complementariedad que decide el diseño del enrutador:

    Cerebras :  5 RPM,  30.000 TPM   → pocas peticiones, mucho token
    Groq     : 30 RPM,   8-12.000 TPM → muchas peticiones, poco token

Las llamadas de enriquecimiento y repertorios mandan ~10.000 tokens de
entrada. En Groq no entran NUNCA: una sola petición excede el TPM del modelo.
Por eso el ruteo no puede ser por capa, tiene que ser por tamaño de payload
además de por calidad requerida. El enrutador descarta solo los modelos donde
la petición no cabe.

Todo el catálogo es configurable con la variable MODEL_POOL (JSON), para
poder ajustar límites cuando el proveedor los cambie sin tocar código.
"""
from __future__ import annotations

import json
import logging
import os

from .ratelimit import ModelLimiter

logger = logging.getLogger(__name__)


# tier: 'alta' para razonamiento y esquemas complejos, 'media' para extracción
# mecánica de volumen. El enrutador nunca baja de tier, solo puede subir.
DEFAULT_POOL: list[dict] = [
    # ── Cerebras: pocas peticiones, mucho token. Único apto para payloads grandes.
    {"key": "cerebras:gpt-oss-120b", "provider": "cerebras", "model": "gpt-oss-120b",
     "tier": "alta", "rpm": 5, "tpm": 30_000, "tpd": 1_000_000, "max_output": 8000},
    {"key": "cerebras:zai-glm-4.7", "provider": "cerebras", "model": "zai-glm-4.7",
     "tier": "alta", "rpm": 5, "tpm": 30_000, "tpd": 1_000_000, "max_output": 8000,
     "nota": "Preview. Deprecación anunciada para 2026-08-17."},
    {"key": "cerebras:gemma-4-31b", "provider": "cerebras", "model": "gemma-4-31b",
     "tier": "media", "rpm": 5, "tpm": 30_000, "tpd": 1_000_000, "max_output": 8000,
     "nota": "Preview."},

    # ── Groq: muchas peticiones, poco token. Solo para llamadas chicas.
    {"key": "groq:llama-3.3-70b", "provider": "groq", "model": "llama-3.3-70b-versatile",
     "tier": "alta", "rpm": 30, "tpm": 12_000, "tpd": 100_000, "max_output": 8000},
    {"key": "groq:gpt-oss-120b", "provider": "groq", "model": "openai/gpt-oss-120b",
     "tier": "alta", "rpm": 30, "tpm": 8_000, "tpd": 200_000, "max_output": 8000},
    {"key": "groq:qwen3.6-27b", "provider": "groq", "model": "qwen/qwen3.6-27b",
     "tier": "media", "rpm": 30, "tpm": 8_000, "tpd": 200_000, "max_output": 8000},
]

TIER_RANK = {"media": 0, "alta": 1}


class NoCapacity(Exception):
    """Ningún modelo del pool puede atender esta petición."""


class ModelPool:
    def __init__(self, entries: list[dict] | None = None) -> None:
        entries = entries or _load_pool()
        self.entries: list[dict] = []
        self.limiters: dict[str, ModelLimiter] = {}

        for entry in entries:
            provider = entry["provider"]
            token_env = {"cerebras": "CEREBRAS_API_KEY", "groq": "GROQ_API_KEY",
                         "gemini": "GOOGLE_API_KEY", "hf": "HF_TOKEN",
                         "claude": "ANTHROPIC_API_KEY"}.get(provider)
            if token_env and not os.environ.get(token_env):
                logger.info("[pool] %s desactivado: falta %s", entry["key"], token_env)
                continue
            self.entries.append(entry)
            self.limiters[entry["key"]] = ModelLimiter(
                key=entry["key"],
                rpm=entry["rpm"],
                tpm=entry["tpm"],
                rpd=entry.get("rpd"),
                tpd=entry.get("tpd"),
            )

        if not self.entries:
            raise RuntimeError(
                "El pool de modelos quedó vacío: no hay ninguna API key configurada."
            )
        logger.info("[pool] %d modelos activos: %s",
                    len(self.entries), [e["key"] for e in self.entries])

    def capacity_summary(self) -> dict:
        return {
            "modelos": [e["key"] for e in self.entries],
            "tpm_total": sum(e["tpm"] for e in self.entries),
            "rpm_total": sum(e["rpm"] for e in self.entries),
            "tpd_total": sum(e.get("tpd") or 0 for e in self.entries),
        }

    def candidates(self, tier: str, estimated_tokens: float) -> list[dict]:
        """Modelos que pueden atender esta petición, mejor primero.

        Se descartan por tres motivos distintos y conviene no confundirlos:
        calidad insuficiente, la petición no cabe en su TPM, o cupo diario agotado.
        """
        wanted = TIER_RANK.get(tier, 1)
        viables = []
        for entry in self.entries:
            if TIER_RANK.get(entry["tier"], 0) < wanted:
                continue
            if entry["tpm"] < estimated_tokens:
                continue  # no cabe ni con la cubeta llena
            limiter = self.limiters[entry["key"]]
            if limiter.exhausted(estimated_tokens):
                continue
            viables.append(entry)

        # Preferimos el que esté disponible antes; a igualdad, el de más cupo libre.
        def orden(entry):
            limiter = self.limiters[entry["key"]]
            return (limiter.wait_time(estimated_tokens), -limiter.tokens.peek())

        viables.sort(key=orden)
        return viables

    async def acquire(self, tier: str, estimated_tokens: float) -> tuple[dict, float]:
        """Elige modelo, espera su cupo y lo reserva. Devuelve (entrada, segundos esperados)."""
        viables = self.candidates(tier, estimated_tokens)
        if not viables and tier == "media":
            viables = self.candidates("alta", estimated_tokens)  # subir de tier sí, bajar no
        if not viables:
            raise NoCapacity(
                f"Ningún modelo disponible para tier={tier} y ~{estimated_tokens:.0f} tokens. "
                f"Puede ser cupo diario agotado o un techo de tokens demasiado alto para esa capa."
            )
        elegido = viables[0]
        waited = await self.limiters[elegido["key"]].acquire(estimated_tokens)
        return elegido, waited

    def penalize(self, key: str, seconds: float) -> None:
        if key in self.limiters:
            self.limiters[key].penalize(seconds)

    def sync(self, key: str, headers: dict) -> None:
        if key in self.limiters:
            self.limiters[key].sync_from_headers(headers)

    def stats(self) -> dict:
        return {
            key: {
                "llamadas": lim.stats["acquired"],
                "espera_s": round(lim.stats["waited_seconds"], 1),
                "rechazos_429": lim.stats["rejected_429"],
                "tokens_dia_usados": int(lim.daily_tokens.used) if lim.daily_tokens else None,
            }
            for key, lim in self.limiters.items()
            if lim.stats["acquired"] or lim.stats["rejected_429"]
        }


def _load_pool() -> list[dict]:
    raw = os.environ.get("MODEL_POOL")
    if not raw:
        return DEFAULT_POOL
    try:
        entries = json.loads(raw)
        if isinstance(entries, list) and entries:
            logger.info("[pool] Usando MODEL_POOL del entorno (%d entradas)", len(entries))
            return entries
    except json.JSONDecodeError as e:
        logger.error("[pool] MODEL_POOL no es JSON válido (%s); se usa el pool por defecto", e)
    return DEFAULT_POOL


_POOL: ModelPool | None = None


def get_pool() -> ModelPool:
    global _POOL
    if _POOL is None:
        _POOL = ModelPool()
    return _POOL


def reset_pool() -> None:
    """Para tests y para reiniciar contadores diarios."""
    global _POOL
    _POOL = None
