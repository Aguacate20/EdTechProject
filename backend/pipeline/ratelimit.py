"""
pipeline/ratelimit.py — NUEVO en v2.2

Limitador propio, por modelo, que evita el 429 en vez de reaccionar a él.

En la corrida medida hubo ~64 llamadas exitosas y ~35 rechazadas con 429.
Cada rechazo cuesta un minuto de espera, así que más de la mitad del tiempo
total se fue en castigos por pedir cuando no había cupo. El cliente ya sabía
reaccionar al 429; lo que faltaba era no provocarlo.

Los proveedores usan token bucket con reposición continua, así que se replica
esa misma mecánica del lado del cliente: la capacidad se recupera de forma
gradual en vez de resetearse por intervalos.

Detalle importante sobre cómo se cuenta: los proveedores estiman el consumo
ANTES de procesar, sumando los tokens de entrada más el techo de salida
declarado. Por eso aquí se reserva `entrada_estimada + max_tokens`, no el
consumo real. Declarar un techo de 6.000 tokens para una respuesta de 2.000
gasta 6.000 de cuota igual.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    """Cubeta con reposición continua."""

    def __init__(self, capacity: float, refill_per_second: float) -> None:
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self.available = float(capacity)
        self.updated_at = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated_at
        if elapsed > 0:
            self.available = min(
                self.capacity, self.available + elapsed * self.refill_per_second
            )
            self.updated_at = now

    def peek(self) -> float:
        self._refill()
        return self.available

    def wait_time(self, amount: float) -> float:
        """Segundos hasta que haya cupo para `amount`. 0 si ya lo hay."""
        self._refill()
        if amount > self.capacity:
            # No cabe ni con la cubeta llena: es un error de configuración,
            # no algo que esperando se resuelva.
            return float("inf")
        if self.available >= amount:
            return 0.0
        faltante = amount - self.available
        return faltante / self.refill_per_second if self.refill_per_second > 0 else float("inf")

    def consume(self, amount: float) -> None:
        self._refill()
        self.available -= amount


class DailyCounter:
    """Cupo diario simple. No se reposita: si se agota, ese modelo sale del pool."""

    def __init__(self, limit: float) -> None:
        self.limit = float(limit)
        self.used = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit - self.used)

    def can_afford(self, amount: float) -> bool:
        return self.remaining >= amount

    def consume(self, amount: float) -> None:
        self.used += amount


class ModelLimiter:
    """Límites combinados de un modelo: peticiones y tokens, por minuto y por día."""

    def __init__(
        self,
        key: str,
        rpm: int,
        tpm: int,
        rpd: int | None = None,
        tpd: int | None = None,
    ) -> None:
        self.key = key
        self.rpm = rpm
        self.tpm = tpm
        self.requests = TokenBucket(rpm, rpm / 60.0)
        self.tokens = TokenBucket(tpm, tpm / 60.0)
        self.daily_requests = DailyCounter(rpd) if rpd else None
        self.daily_tokens = DailyCounter(tpd) if tpd else None
        self.lock = asyncio.Lock()
        self.stats = {"acquired": 0, "waited_seconds": 0.0, "rejected_429": 0}

    def exhausted(self, estimated_tokens: float) -> bool:
        """Cupo diario agotado: el modelo sale del pool hasta mañana."""
        if self.daily_requests and not self.daily_requests.can_afford(1):
            return True
        if self.daily_tokens and not self.daily_tokens.can_afford(estimated_tokens):
            return True
        return False

    def wait_time(self, estimated_tokens: float) -> float:
        return max(
            self.requests.wait_time(1),
            self.tokens.wait_time(estimated_tokens),
        )

    async def acquire(self, estimated_tokens: float) -> float:
        """Espera hasta tener cupo y lo reserva. Devuelve los segundos esperados."""
        waited = 0.0
        async with self.lock:
            while True:
                delay = self.wait_time(estimated_tokens)
                if delay == float("inf"):
                    raise ValueError(
                        f"{self.key}: una petición de ~{estimated_tokens:.0f} tokens no cabe "
                        f"en el límite de {self.tpm} por minuto. Bajá el techo de esa capa "
                        f"o mandala a un modelo con más TPM."
                    )
                if delay <= 0:
                    break
                waited += delay
                logger.debug("[ratelimit] %s: esperando %.1fs", self.key, delay)
                await asyncio.sleep(delay)

            self.requests.consume(1)
            self.tokens.consume(estimated_tokens)
            if self.daily_requests:
                self.daily_requests.consume(1)
            if self.daily_tokens:
                self.daily_tokens.consume(estimated_tokens)

        self.stats["acquired"] += 1
        self.stats["waited_seconds"] += waited
        return waited

    def penalize(self, seconds: float) -> None:
        """El proveedor devolvió 429 pese al limitador: nuestra estimación se
        quedó corta. Se vacían las cubetas para no insistir."""
        self.stats["rejected_429"] += 1
        self.requests.available = 0.0
        self.tokens.available = 0.0
        now = time.monotonic()
        # Retrasar el reloj de reposición equivale a esperar.
        self.requests.updated_at = now + max(0.0, seconds)
        self.tokens.updated_at = now + max(0.0, seconds)

    def sync_from_headers(self, headers: dict) -> None:
        """Ajusta las cubetas con el cupo real que informa el proveedor.

        Nuestra estimación de tokens de entrada es aproximada; las cabeceras
        traen el número verdadero. Sincronizar evita que la deriva acumulada
        nos vuelva demasiado optimistas o demasiado tímidos.
        """
        def _num(*names):
            for name in names:
                value = headers.get(name)
                if value is None:
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
            return None

        remaining_tokens = _num(
            "x-ratelimit-remaining-tokens-minute", "x-ratelimit-remaining-tokens"
        )
        if remaining_tokens is not None:
            self.tokens.available = min(self.tokens.capacity, remaining_tokens)
            self.tokens.updated_at = time.monotonic()

        remaining_requests = _num(
            "x-ratelimit-remaining-requests-minute", "x-ratelimit-remaining-requests"
        )
        if remaining_requests is not None:
            self.requests.available = min(self.requests.capacity, remaining_requests)
            self.requests.updated_at = time.monotonic()

        remaining_daily = _num("x-ratelimit-remaining-tokens-day")
        if remaining_daily is not None and self.daily_tokens:
            self.daily_tokens.used = max(
                self.daily_tokens.used, self.daily_tokens.limit - remaining_daily
            )


def estimate_input_tokens(*texts: str) -> int:
    """Estimación conservadora. ~3.5 caracteres por token para español e inglés.

    Se redondea hacia arriba a propósito: subestimar produce 429, que cuesta un
    minuto; sobreestimar produce una espera de segundos.
    """
    total_chars = sum(len(t or "") for t in texts)
    return int(total_chars / 3.3) + 200
