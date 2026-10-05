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
# v3.13 · fuera zai-glm-4.7, gemma-4-31b, qwen3.6-27b y gemma-4-26b: devolvían 404 y se
# llevaban capas enteras (canonicalización y casos). Los presupuestos de los que quedan:
# modelos en preview son conservadores a propósito: el de zai-glm-4.7 estaba
# medido contra un error real y el de gemma-4-31b se asume igual mientras no
# haya dato. Quedarse corto solo manda las llamadas grandes al modelo de
# ventana amplia; pasarse hace fallar una capa entera.
DEFAULT_POOL: list[dict] = [
    # v3.22 · Cerebras fuera: cerró su plan gratuito (402 en cada llamada).

    # ── Groq: muchas peticiones, poco token. Solo para llamadas chicas.
    {"key": "groq:gpt-oss-120b", "provider": "groq", "model": "openai/gpt-oss-120b",
     "tier": "alta", "rpm": 30, "tpm": 8_000, "tpd": 200_000,
     "max_output": 8000, "context_limit": 131_000},

    # ── v3.23 · NVIDIA Build: gratis sin tarjeta, 40 peticiones por minuto y sin
    # tope de tokens publicado. Candidato a hacer las capas grandes. Los nombres
    # que NVIDIA no liste se retiran solos al arrancar.
    {"key": "nvidia:gpt-oss-120b", "provider": "nvidia", "model": "openai/gpt-oss-120b",
     "tier": "alta", "rpm": 30, "tpm": 300_000, "tpd": 20_000_000,
     "max_output": 8000, "context_limit": 120_000, "token_param": "max_tokens",
     "espera_429_s": 15.0},
    {"key": "nvidia:llama-3.3-70b", "provider": "nvidia", "model": "meta/llama-3.3-70b-instruct",
     "tier": "alta", "rpm": 30, "tpm": 300_000, "tpd": 20_000_000,
     "max_output": 8000, "context_limit": 120_000, "token_param": "max_tokens",
     "latency_penalty_s": 3.0, "espera_429_s": 15.0},

    # ── v3.23 · OpenRouter gratis: 50 peticiones al día (unos dos PDF). Respaldo.
    # v3.24 · los gratuitos grandes que la cuenta lista hoy (no hay gpt-oss ni llama).
    # v3.25 · último recurso: medidos a 80-300 s por llamada, detrás de Gemini.
    # v3.27 · medido en /experimento/openrouter: Nemotron Super SIN razonamiento
    # respondió en 2,8 s (razonando, su hermano Ultra tardaba 80-300 s). Va primero
    # para las capas grandes; los demás quedan de último recurso.
    {"key": "openrouter:nemotron-super", "provider": "openrouter", "model": "nvidia/nemotron-3-super-120b-a12b:free",
     "tier": "alta", "rpm": 15, "tpm": 200_000, "rpd": 50, "tpd": 5_000_000,
     "max_output": 8000, "context_limit": 120_000, "token_param": "max_tokens",
     "latency_penalty_s": 0.0, "espera_429_s": 30.0, "extra_body": {"reasoning": {"enabled": False}}},
    {"key": "openrouter:nemotron-ultra", "provider": "openrouter", "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
     "tier": "alta", "rpm": 15, "tpm": 200_000, "rpd": 50, "tpd": 5_000_000,
     "max_output": 8000, "context_limit": 120_000, "token_param": "max_tokens",
     "latency_penalty_s": 20.0, "espera_429_s": 30.0, "extra_body": {"reasoning": {"enabled": False}}},
    {"key": "openrouter:gemma-4-31b", "provider": "openrouter", "model": "google/gemma-4-31b-it:free",
     "tier": "alta", "rpm": 15, "tpm": 200_000, "rpd": 50, "tpd": 5_000_000,
     "max_output": 8000, "context_limit": 120_000, "token_param": "max_tokens",
     "latency_penalty_s": 220.0, "espera_429_s": 30.0},

    # v3.24 · Mistral fuera: medium y small respondieron 429 a todas las llamadas
    # durante una tarde entera pese a tener cupo en el panel; solo añadían espera.

    # ── Google: lento pero de ventana enorme y cupo aparte. Red de seguridad.
    #
    # No es una alternativa a los de arriba, es lo que evita perder una capa
    # cuando todos los demás están agotados o la petición no cabe en ninguna
    # ventana. La penalización de latencia hace que el enrutador lo elija solo
    # en ese caso: preferimos tardar tres minutos a devolver una capa vacía.
    {"key": "gemini:flash", "provider": "gemini", "model": "gemini-flash-latest",
     "tier": "alta", "rpm": 15, "tpm": 250_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 1_000_000,
     "latency_penalty_s": 120.0,
     "nota": "Último recurso de tier alta. Ventana muy amplia."},

    # ── v3.18 · segunda y tercera red de seguridad en Google, con cupo aparte.
    # Cuando Flash responde 503 (saturación) y la petición no cabe en Groq, sin
    # esto la capa se pierde. Si Google no lista alguno de estos nombres, la
    # verificación de arranque lo retira sola: añadirlos no puede romper nada.
    {"key": "gemini:flash-lite", "provider": "gemini", "model": "gemini-flash-lite-latest",
     "tier": "alta", "rpm": 15, "tpm": 250_000, "tpd": 1_000_000,
     "max_output": 8000, "context_limit": 1_000_000,
     "latency_penalty_s": 150.0},
    # v3.29 · Gemma por Google AI Studio como ÚLTIMA opción: cuando se acaban las
    # 50 peticiones de OpenRouter y Gemini Flash no tiene cuota, la extracción
    # termina igual, solo que despacio. Los nombres que Google no liste se retiran solos.
    {"key": "gemini:gemma-4-31b", "provider": "gemini", "model": "gemma-4-31b-it",
     "tier": "alta", "rpm": 25, "tpm": 15_000, "tpd": 10_000_000,
     "max_output": 8000, "context_limit": 120_000,
     "latency_penalty_s": 400.0, "timeout_s": 420.0, "espera_429_s": 30.0,
     "nota": "Red final: lento (minutos por llamada) pero con cupo diario amplio."},
    {"key": "gemini:gemma-4-26b", "provider": "gemini", "model": "gemma-4-26b-a4b-it",
     "tier": "alta", "rpm": 25, "tpm": 15_000, "tpd": 10_000_000,
     "max_output": 8000, "context_limit": 120_000,
     "latency_penalty_s": 410.0, "timeout_s": 420.0, "espera_429_s": 30.0,
     "nota": "Red final: lento (minutos por llamada) pero con cupo diario amplio."},
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
                         "gemini": "GOOGLE_API_KEY", "mistral": "MISTRAL_API_KEY", "nvidia": "NVIDIA_API_KEY",
                         "openrouter": "OPENROUTER_API_KEY", "hf": "HF_TOKEN",
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

    # ── v3.14 · el pool se cuida solo ──────────────────────────────────────────
    def desactivar(self, key: str, motivo: str) -> None:
        """Cuarentena en caliente: un modelo que ya no existe (404) no se vuelve a probar."""
        antes = len(self.entries)
        self.entries = [e for e in self.entries if e.get("key") != key]
        if len(self.entries) < antes:
            self.retirados = getattr(self, "retirados", {})
            self.retirados[key] = motivo
            logger.warning("[pool] %s retirado del pool: %s · quedan %d", key, motivo, len(self.entries))

    async def verificar_con_proveedores(self) -> dict:
        """Al arrancar: cada proveedor dice qué modelos tiene; los de la lista que ya no existan
        salen del pool. Si un proveedor no responde, sus modelos se dejan como están (no se
        castiga un fallo de red como si fuera un modelo muerto)."""
        import os
        import httpx
        listados = {
            "cerebras": ("https://api.cerebras.ai/v1/models", "CEREBRAS_API_KEY"),
            "groq": ("https://api.groq.com/openai/v1/models", "GROQ_API_KEY"),
            "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/models", "GEMINI_API_KEY"),
            "mistral": ("https://api.mistral.ai/v1/models", "MISTRAL_API_KEY"),
            "nvidia": ("https://integrate.api.nvidia.com/v1/models", "NVIDIA_API_KEY"),
            "openrouter": ("https://openrouter.ai/api/v1/models", "OPENROUTER_API_KEY"),
        }
        informe: dict = {"verificados": {}, "retirados": [], "sin_respuesta": []}
        async with httpx.AsyncClient(timeout=15) as cli:
            for proveedor, (url, token_env) in listados.items():
                token = os.environ.get(token_env) or os.environ.get("GOOGLE_API_KEY") if proveedor == "gemini" else os.environ.get(token_env)
                mios = [e for e in self.entries if e.get("provider") == proveedor]
                if not mios or not token:
                    continue
                try:
                    r = await cli.get(url, headers={"Authorization": f"Bearer {token}"})
                    r.raise_for_status()
                    datos = r.json()
                    ids = {str(m.get("id") or m.get("name") or "").split("/")[-1] for m in (datos.get("data") or datos.get("models") or [])}
                except Exception as e:  # noqa: BLE001
                    informe["sin_respuesta"].append(f"{proveedor}: {e}")
                    continue
                informe["verificados"][proveedor] = len(ids)
                if proveedor == "gemini":
                    logger.info("[pool] google ofrece gemma: %s", sorted(i for i in ids if "gemma" in i))
                if proveedor == "nvidia":
                    # v3.23 · diagnóstico: los modelos grandes que ofrece la cuenta
                    logger.info("[pool] nvidia ofrece: %s", sorted(
                        i for i in ids if any(t in i for t in (
                            "gpt-oss", "llama-3.3", "llama-4", "qwen", "deepseek", "nemotron", "gemma", "mistral")))[:60])
                if proveedor == "openrouter":
                    logger.info("[pool] openrouter gratis: %s", sorted(i for i in ids if i.endswith(":free")))
                for e in mios:
                    if e.get("sin_verificar"):
                        continue
                    modelo = str(e.get("model", "")).split("/")[-1]
                    if ids and modelo not in ids and not any(modelo in x or x in modelo for x in ids):
                        self.desactivar(e["key"], f"el proveedor ya no lo lista ({modelo})")
                        informe["retirados"].append(e["key"])
        logger.info("[pool] verificación: %s", informe)
        return informe

    def estado(self) -> dict:
        return {
            "activos": [e["key"] for e in self.entries],
            "retirados": getattr(self, "retirados", {}),
        }

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

    async def acquire(self, tier: str, estimated_tokens: float,
                      evitar: list[str] | None = None) -> tuple[dict, float]:
        """Elige modelo, espera su cupo y lo reserva. Devuelve (entrada, segundos esperados).

        v3.19 · `evitar`: los que ya fallaron en esta misma llamada van al final.
        Sin esto, un modelo saturado (503) se reintentaba cinco veces mientras
        otro sano esperaba detrás por su penalización de latencia."""
        viables = self.candidates(tier, estimated_tokens)
        if not viables and tier == "media":
            viables = self.candidates("alta", estimated_tokens)  # subir de tier sí, bajar no
        if evitar:
            viables.sort(key=lambda e: evitar.count(e["key"]))  # estable: conserva el orden entre iguales
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
