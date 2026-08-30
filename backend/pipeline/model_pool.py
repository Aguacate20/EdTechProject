"""
pipeline/model_pool.py — v2.2.3

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

## Añadido en v2.2.2: ventana de contexto

La v2.2 modelaba la cuota por minuto pero NO la ventana de contexto, y son
restricciones distintas. La capa de intuiciones manda ~10.000 tokens; el
enrutador la mandó a `zai-glm-4.7` porque cabía de sobra en sus 30.000 tokens
por minuto, sin saber que su ventana es de 8.192. La capa entera falló con
`context_length_exceeded` y el documento se quedó sin repertorios.

Ahora cada modelo declara `context_limit` y el enrutador verifica las dos
cosas. Además, cuando un proveedor rechaza por longitud informa su límite real
en el mensaje, así que ese número se aprende: si mañana cambian los topes, el
sistema se entera solo en vez de perder una capa.
"""
from __future__ import annotations

import json
import logging
import os

from .ratelimit import ModelLimiter

logger = logging.getLogger(__name__)


# tier: 'alta' para razonamiento y esquemas complejos, 'media' para extracción
# mecánica de volumen. El enrutador nunca baja de tier, solo puede subir.
# `context_limit` es la ventana total (entrada + salida). Los valores de los
# modelos en preview son conservadores a propósito: el de zai-glm-4.7 está
# medido contra un error real y el de gemma-4-31b se asume igual mientras no
# haya dato. Quedarse corto solo manda las llamadas grandes al modelo de
# ventana amplia; pasarse hace fallar una capa entera.
DEFAULT_POOL: list[dict] = [
    # ── Cerebras: pocas peticiones, mucho token. Único apto para payloads grandes.
    {"key": "cerebras:gpt-oss-120b", "provider": "cerebras", "model": "gpt-oss-120b",
     "tier": "alta", "rpm": 5, "tpm": 30_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 65_536},
    {"key": "cerebras:zai-glm-4.7", "provider": "cerebras", "model": "zai-glm-4.7",
     "tier": "alta", "rpm": 5, "tpm": 30_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 8_192,
     "nota": "Preview. Ventana medida contra un error real. Deprecación 2026-08-17."},
    {"key": "cerebras:gemma-4-31b", "provider": "cerebras", "model": "gemma-4-31b",
     "tier": "media", "rpm": 5, "tpm": 30_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 8_192,
     "nota": "Preview. Ventana asumida por prudencia."},

    # ── Groq: muchas peticiones, poco token. Solo para llamadas chicas.
    {"key": "groq:llama-3.3-70b", "provider": "groq", "model": "llama-3.3-70b-versatile",
     "tier": "alta", "rpm": 30, "tpm": 12_000, "tpd": 100_000,
     "max_output": 8000, "context_limit": 128_000},
    {"key": "groq:gpt-oss-120b", "provider": "groq", "model": "openai/gpt-oss-120b",
     "tier": "alta", "rpm": 30, "tpm": 8_000, "tpd": 200_000,
     "max_output": 8000, "context_limit": 131_000},
    {"key": "groq:qwen3.6-27b", "provider": "groq", "model": "qwen/qwen3.6-27b",
     "tier": "media", "rpm": 30, "tpm": 8_000, "tpd": 200_000,
     "max_output": 8000, "context_limit": 32_000},

    # ── Google: lento pero de ventana enorme y cupo aparte. Red de seguridad.
    #
    # No es una alternativa a los de arriba, es lo que evita perder una capa
    # cuando todos los demás están agotados o la petición no cabe en ninguna
    # ventana. La penalización de latencia hace que el enrutador lo elija solo
    # en ese caso: preferimos tardar tres minutos a devolver una capa vacía.
    {"key": "gemini:gemma-4-26b", "provider": "gemini", "model": "gemma-4-26b-a4b-it",
     "tier": "media", "rpm": 30, "tpm": 15_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 128_000,
     "latency_penalty_s": 150.0,
     "nota": "Último recurso. Free tier con colas de minutos."},
    {"key": "gemini:flash", "provider": "gemini", "model": "gemini-flash-latest",
     "tier": "alta", "rpm": 15, "tpm": 250_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 1_000_000,
     "latency_penalty_s": 120.0,
     "nota": "Último recurso de tier alta. Ventana muy amplia."},
]

DEFAULT_CONTEXT_LIMIT = 8_192

TIER_RANK = {"media": 0, "alta": 1}

# Penalización de latencia. El enrutador ordena por "cuándo puedo tener esto
# resuelto", así que un modelo lento se elige solo cuando los rápidos no están
# disponibles. Medido: Gemma en Google AI Studio tardó entre 107 y 224 segundos
# por llamada donde Cerebras tarda 1,1 — no es el modelo, es la cola del free
# tier. Sigue siendo mejor que perder una capa entera.
DEFAULT_LATENCY_PENALTY_S = 0.0


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
            "ultimo_recurso": [
                e["key"] for e in self.entries
                if e.get("latency_penalty_s", DEFAULT_LATENCY_PENALTY_S) > 0
            ],
            "ventanas": {
                e["key"]: e.get("context_limit", DEFAULT_CONTEXT_LIMIT) for e in self.entries
            },
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
            if entry.get("context_limit", DEFAULT_CONTEXT_LIMIT) < estimated_tokens:
                continue  # no cabe en la ventana de contexto del modelo
            if entry["tpm"] < estimated_tokens:
                continue  # no cabe ni con la cubeta de cuota llena
            limiter = self.limiters[entry["key"]]
            if limiter.exhausted(estimated_tokens):
                continue
            viables.append(entry)

        # Se ordena por "cuándo tendría esto resuelto": espera por cuota más la
        # latencia típica del modelo. Así un proveedor lento con cupo libre no le
        # gana a uno rápido que estará disponible en cinco segundos, pero sí se
        # elige cuando la alternativa es esperar un minuto o no tener a nadie.
        def orden(entry):
            limiter = self.limiters[entry["key"]]
            penalty = entry.get("latency_penalty_s", DEFAULT_LATENCY_PENALTY_S)
            return (limiter.wait_time(estimated_tokens) + penalty, -limiter.tokens.peek())

        viables.sort(key=orden)
        return viables

    async def acquire(self, tier: str, estimated_tokens: float) -> tuple[dict, float]:
        """Elige modelo, espera su cupo y lo reserva. Devuelve (entrada, segundos esperados)."""
        viables = self.candidates(tier, estimated_tokens)
        if not viables and tier == "media":
            viables = self.candidates("alta", estimated_tokens)  # subir de tier sí, bajar no
        if not viables:
            ventanas = [e.get("context_limit", DEFAULT_CONTEXT_LIMIT) for e in self.entries]
            mayor = max(ventanas) if ventanas else 0
            motivo = (
                f"excede la ventana de todos los modelos (la mayor es {mayor}); "
                f"hay que bajar el presupuesto de esa capa"
                if estimated_tokens > mayor
                else "puede ser cupo diario agotado o un techo de tokens demasiado alto"
            )
            raise NoCapacity(
                f"Ningún modelo para tier={tier} y ~{estimated_tokens:.0f} tokens: {motivo}."
            )
        elegido = viables[0]
        waited = await self.limiters[elegido["key"]].acquire(estimated_tokens)
        return elegido, waited

    def penalize(self, key: str, seconds: float) -> None:
        if key in self.limiters:
            self.limiters[key].penalize(seconds)

    def learn_context_limit(self, key: str, limit: int) -> None:
        """Guarda la ventana real que informó el proveedor al rechazar por longitud."""
        for entry in self.entries:
            if entry["key"] != key:
                continue
            anterior = entry.get("context_limit", DEFAULT_CONTEXT_LIMIT)
            if limit and limit < anterior:
                entry["context_limit"] = limit
                logger.warning("[pool] %s: ventana corregida de %s a %s", key, anterior, limit)
            return

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
