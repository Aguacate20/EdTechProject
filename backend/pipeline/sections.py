"""
pipeline/sections.py — NUEVO en v2

Enrutamiento de segmentos por sección.

El problema que resuelve: en v1 cada capa recibía un prefijo del documento
(`segments[:5]` para repertorios, `segments[:8]` para argumentación y casos).
En un paper académico —intro, marco teórico, método, resultados, discusión,
conclusión— eso significa que la capa 5 buscaba casos y evidencia empírica en
la introducción, y la capa 4 buscaba el debate teórico en el marco teórico.
Las dos leían justo las secciones donde su materia prima no está.

Esto no es un problema de presupuesto de tokens sino de enrutamiento: la
segmentación ya captura `section_title` y se estaba descartando.

Fallback: muchos PDFs no tienen headings detectables. Si la clasificación no
encuentra las secciones que una capa necesita, se cae a una heurística
posicional adecuada para esa capa (no al prefijo, que era el error original).
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Iterable


class SectionKind(str, Enum):
    ABSTRACT = "abstract"
    INTRO = "intro"
    THEORY = "theory"
    METHOD = "method"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    BACKMATTER = "backmatter"   # referencias, apéndices, agradecimientos
    OTHER = "other"


# Patrones ES/EN. El orden importa: se evalúa de arriba abajo.
_PATTERNS: list[tuple[SectionKind, str]] = [
    (SectionKind.BACKMATTER, r"referenc|bibliograf|apéndic|apendic|appendix|acknowledg|agradecim|anexo|funding|conflict of interest|declaration"),
    (SectionKind.ABSTRACT, r"^\s*(abstract|resumen|summary)\b"),
    (SectionKind.CONCLUSION, r"conclusi|closing remarks|final remarks|consideraciones finales"),
    (SectionKind.DISCUSSION, r"discusi|discussion|general discussion|implicacion|implications|limitacion|limitations"),
    (SectionKind.RESULTS, r"resultad|results|findings|hallazgos|análisis de datos|analisis de datos|data analysis|experiment \d|estudio \d|study \d"),
    (SectionKind.METHOD, r"m[ée]todo|method|materials|participant|procedimiento|procedure|muestra|sample|dise[ñn]o|design|instrument|medida|measures"),
    (SectionKind.THEORY, r"marco te[óo]rico|theoretical|background|literature|estado del arte|related work|antecedent|revisi[óo]n|framework|fundament"),
    (SectionKind.INTRO, r"^\s*(1\.?\s*)?(introducci[óo]n|introduction)\b|planteamiento|the present study|el presente estudio"),
]


def classify_section(title: str | None) -> SectionKind:
    if not title:
        return SectionKind.OTHER
    t = title.strip().lower()
    for kind, pattern in _PATTERNS:
        if re.search(pattern, t):
            return kind
    return SectionKind.OTHER


# Qué secciones alimenta cada capa, en orden de preferencia.
# El razonamiento por capa está en el comentario de cada entrada.
LAYER_ROUTES: dict[str, list[SectionKind]] = {
    # Los conceptos están en todo el documento; solo se excluye el backmatter.
    "concepts": [
        SectionKind.ABSTRACT, SectionKind.INTRO, SectionKind.THEORY,
        SectionKind.METHOD, SectionKind.RESULTS, SectionKind.DISCUSSION,
        SectionKind.CONCLUSION, SectionKind.OTHER,
    ],
    # Las relaciones se argumentan en el marco teórico y se revisan en discusión.
    "relations": [
        SectionKind.THEORY, SectionKind.DISCUSSION, SectionKind.INTRO,
        SectionKind.CONCLUSION, SectionKind.OTHER,
    ],
    # El enriquecimiento necesita el arco completo del concepto en el paper.
    "enrichment": [
        SectionKind.INTRO, SectionKind.THEORY, SectionKind.RESULTS,
        SectionKind.DISCUSSION, SectionKind.CONCLUSION, SectionKind.OTHER,
    ],
    # Las intuiciones cotidianas se nombran al motivar el problema (intro) y al
    # interpretar los resultados contra el sentido común (discusión).
    "repertoires": [
        SectionKind.INTRO, SectionKind.DISCUSSION, SectionKind.THEORY,
        SectionKind.CONCLUSION,
    ],
    # El debate teórico vive en discusión y conclusión, no en el marco teórico.
    "arguments": [
        SectionKind.DISCUSSION, SectionKind.CONCLUSION, SectionKind.THEORY,
        SectionKind.INTRO,
    ],
    # Los casos, experimentos y datos viven en resultados y método.
    "cases": [
        SectionKind.RESULTS, SectionKind.METHOD, SectionKind.DISCUSSION,
        SectionKind.THEORY,
    ],
}

# Fracción del documento a usar como fallback cuando no hay headings útiles.
# (inicio, fin) en proporción sobre la lista de segmentos.
_FALLBACK_SPANS: dict[str, tuple[float, float]] = {
    "concepts": (0.0, 1.0),
    "relations": (0.0, 0.7),
    "enrichment": (0.0, 1.0),
    "repertoires": (0.0, 0.35),     # más el último tramo, ver select_for_layer
    "arguments": (0.55, 1.0),
    "cases": (0.30, 0.90),
}

_FALLBACK_EXTRA_TAIL = {"repertoires"}


class AnnotatedSegment:
    """Proxy usado solo si el TextSegment original no admite atributos nuevos
    (dataclass congelada o con __slots__). Delega todo lo demás al original."""

    __slots__ = ("_inner", "kind")

    def __init__(self, inner, kind):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "kind", kind)

    def __getattr__(self, item):
        return getattr(object.__getattribute__(self, "_inner"), item)


def annotate(segments: Iterable[Any]) -> list[Any]:
    """Asigna `.kind` a cada segmento. Propaga la última sección conocida hacia
    los segmentos OTHER, que suelen ser continuaciones de la sección anterior."""
    out = []
    last_known = SectionKind.OTHER
    for seg in segments:
        kind = classify_section(getattr(seg, "section_title", None))
        if kind == SectionKind.OTHER and last_known != SectionKind.OTHER:
            kind = last_known
        elif kind != SectionKind.OTHER:
            last_known = kind
        try:
            seg.kind = kind
            out.append(seg)
        except Exception:
            out.append(AnnotatedSegment(seg, kind))
    return out


class MergedSegment:
    """Varios segmentos contiguos de la misma sección, unidos en uno.

    Medido sobre un paper real de Elsevier a dos columnas: los segmentos salían
    de ~1.500 caracteres, no de los 6.000 del tope. Eso multiplicaba las
    llamadas —la capa 5 hizo 14 para un documento de 12 páginas— y cada llamada
    repite el system prompt y el catálogo de conceptos completo. Fusionar antes
    de armar lotes no pierde una palabra y reduce las llamadas a un tercio.
    """

    __slots__ = ("section_title", "text", "pages", "kind", "merged_count")

    def __init__(self, section_title, text, pages, kind, merged_count):
        self.section_title = section_title
        self.text = text
        self.pages = pages
        self.kind = kind
        self.merged_count = merged_count

    @property
    def char_count(self) -> int:
        return len(self.text)


def merge_segments(segments: list[Any], target_chars: int = 6000) -> list[Any]:
    """Une segmentos contiguos de la misma sección hasta acercarse al objetivo."""
    if not segments:
        return []

    out: list[Any] = []
    buffer: list[Any] = []

    def flush():
        if not buffer:
            return
        if len(buffer) == 1:
            out.append(buffer[0])
        else:
            out.append(MergedSegment(
                section_title=getattr(buffer[0], "section_title", "") or "",
                text="\n\n".join(getattr(s, "text", "") for s in buffer),
                pages=sorted({p for s in buffer for p in (getattr(s, "pages", []) or [])}),
                kind=getattr(buffer[0], "kind", SectionKind.OTHER),
                merged_count=len(buffer),
            ))
        buffer.clear()

    for seg in segments:
        size = getattr(seg, "char_count", len(getattr(seg, "text", "")))
        current = sum(getattr(s, "char_count", len(getattr(s, "text", ""))) for s in buffer)
        same_section = bool(buffer) and getattr(seg, "kind", None) == getattr(buffer[0], "kind", None)
        if buffer and (not same_section or current + size > target_chars):
            flush()
        buffer.append(seg)

    flush()
    return out


def strip_backmatter(segments: list[Any]) -> list[Any]:
    return [s for s in segments if getattr(s, "kind", None) != SectionKind.BACKMATTER]


def select_for_layer(
    segments: list[Any],
    layer: str,
    budget_chars: int,
    min_chars: int = 1500,
) -> tuple[list[Any], bool]:
    """Devuelve (segmentos elegidos, hubo_truncamiento).

    Elige por sección según LAYER_ROUTES y respeta un presupuesto de caracteres.
    Si el enrutamiento no consigue material suficiente, cae al span posicional
    de esa capa — nunca a un prefijo genérico.
    """
    if not segments:
        return [], False

    routes = LAYER_ROUTES.get(layer, LAYER_ROUTES["concepts"])
    order = {k: i for i, k in enumerate(routes)}

    doc_index = {id(s): i for i, s in enumerate(segments)}
    candidates = [s for s in segments if getattr(s, "kind", SectionKind.OTHER) in order]
    candidates.sort(key=lambda s: (order[s.kind], doc_index[id(s)]))

    total = sum(getattr(s, "char_count", len(getattr(s, "text", ""))) for s in candidates)
    if total < min_chars:
        candidates = _positional_fallback(segments, layer)

    chosen: list[Any] = []
    used = 0
    truncated = False
    for seg in candidates:
        size = getattr(seg, "char_count", len(getattr(seg, "text", "")))
        if used + size > budget_chars and chosen:
            truncated = True
            continue
        chosen.append(seg)
        used += size

    # Reordenar al orden natural del documento para que el LLM lea coherente.
    chosen.sort(key=lambda s: doc_index.get(id(s), 0))
    return chosen, truncated


def _positional_fallback(segments: list[Any], layer: str) -> list[Any]:
    n = len(segments)
    lo_frac, hi_frac = _FALLBACK_SPANS.get(layer, (0.0, 1.0))
    lo, hi = int(n * lo_frac), max(int(n * hi_frac), 1)
    picked = segments[lo:hi] or segments[:]
    if layer in _FALLBACK_EXTRA_TAIL and n > 3:
        picked = picked + segments[-max(1, n // 4):]
    # Deduplicar preservando orden
    seen, out = set(), []
    for s in picked:
        if id(s) not in seen:
            seen.add(id(s))
            out.append(s)
    return out


def combine(segments: list[Any], with_headers: bool = True) -> str:
    parts = []
    for seg in segments:
        text = getattr(seg, "text", "")
        if with_headers:
            title = getattr(seg, "section_title", "") or "—"
            pages = getattr(seg, "pages", [])
            parts.append(f"[Sección: {title} | páginas {pages}]\n{text}")
        else:
            parts.append(text)
    return "\n\n---\n\n".join(parts)


def coverage_report(segments: list[Any]) -> dict:
    """Para pipeline_stats: qué secciones se detectaron y cuánto texto tiene cada una."""
    report: dict[str, dict] = {}
    for seg in segments:
        kind = getattr(seg, "kind", SectionKind.OTHER)
        key = kind.value if isinstance(kind, SectionKind) else str(kind)
        entry = report.setdefault(key, {"segments": 0, "chars": 0})
        entry["segments"] += 1
        entry["chars"] += getattr(seg, "char_count", len(getattr(seg, "text", "")))
    return report
